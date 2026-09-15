# What this service needs from a node, and does not have

Two things. One is two lines of kernel configuration; the other is a channel that
does not exist in any form. Everything else in `remote-browser` runs on nodo as it
ships, which is why they are worth stating precisely rather than as a wish list.

| | what | without it | cost to the node |
|---|---|---|---|
| **1** | `CONFIG_INPUT=y` + `CONFIG_INPUT_UINPUT=y` in the guest kernel | the stream is **view-only**: you can watch a browser and not touch it | two symbols, tens of KB of `Image`, on every guest |
| **2** | a channel from a guest to one Unix socket on the host | there is **no viewer service**: the pixels have to be collected by a program running outside the node | one spec field, one firewall rule the node already writes, one operator switch |

And two things this service deliberately does **not** ask for, listed because the
obvious reading of "run a browser" is that it needs them: a GPU, and a sound card.

---

## 1. Input

Sunshine injects mouse and keyboard through `/dev/uinput`. Nodo's guest kernel is
built with:

```
# --- No terminal, keyboard or physical NIC: the console is a serial port and the
# --- only network device is virtio-net. ---
# CONFIG_VT is not set
# CONFIG_INPUT is not set
# CONFIG_HID is not set
```
<sub>`bash/guest-kernel/nodo-guest.config`</sub>

The reasoning in that comment is correct and is about **hardware**. A microVM has
no keyboard, so `CONFIG_HID` and `CONFIG_VT` are dead weight, and `CONFIG_INPUT`
is the subsystem those two hang off. What the comment does not cover is `uinput`,
which is not a driver for a device: it is a character device that lets a userspace
process *create* an input device and write events into it. It needs no hardware,
it is the mechanism every remote-desktop and accessibility tool on Linux uses, and
it is off here as a side effect of switching off the bus that real keyboards sit
on.

That file says of itself: *"Keep this file as the single source of truth for what
a Nodo microVM guest can do. Adding a feature here is a decision about every
service on the network."* It is the right standard to hold this to, so the case
has to be made on those terms:

- **What it lets a guest do that it could not before:** create a virtual input
  device inside its own guest and write events to it. There is no host side. A
  `uinput` device is private to the kernel that created it, and a nodo guest
  kernel is one per instance, so nothing crosses a boundary that was not already
  crossed.
- **What it costs every other service:** the `Image` grows by the input core plus
  `uinput`, which is tens of kilobytes on an `Image` measured in megabytes, and
  nothing is registered at boot because no bus enumerates anything.
- **Who else wants it:** every service that drives a graphical program it did not
  write. A test runner, a scraper that has to click, anything wrapping an
  application with no API.

`CONFIG_HID` and `CONFIG_VT` should stay off. The ask is `CONFIG_INPUT=y` and
`CONFIG_INPUT_UINPUT=y`, nothing more.

### Two ways to avoid asking

Both are real, both were considered, and neither is free:

- **Inject through X instead.** The `XTEST` extension puts events into an X server
  from userspace with no kernel involvement at all, which is how `xdotool` and
  every VNC server on Linux work — `x11vnc` needs no `uinput` for exactly this
  reason. Sunshine's Linux input backend is libevdev/uinput and does not have an
  XTEST path, so this means carrying a patch against Sunshine. A content-addressed
  service can do that honestly — the patch is in the tree and in the digest — but
  it is a fork of an actively developed GPL-3.0 project, maintained for one symbol
  the kernel could provide.
- **Drive the browser instead of the desktop.** Chromium's DevTools protocol has
  `Input.dispatchMouseEvent` and `Input.dispatchKeyEvent`, entirely in userspace,
  and this service does not need to control a desktop — it needs to control one
  browser. But the events arrive inside Sunshine, over the GameStream control
  stream, so getting at them means patching Sunshine again, or running input on a
  side channel that no stock client would speak.

Both trade a two-line kernel change for a permanent fork. That is the trade, said
plainly; it is not obviously wrong, and it is not what this repository does.

---

## 2. A display channel

The viewer decodes the stream. Something has to put the result on a screen, and
the screen is on the host of the node the viewer is running on. There is no path
from a nodo guest to it. Not "an awkward path" — none. It is worth walking through
the four mechanisms that look like they would work, because each fails for a
different reason and the reasons are what constrain the fix.

**Shared filesystems do not carry sockets.** `SHARED_FILESYSTEMS.md` describes
`shared`/`guest` xattrs materialised over virtiofs, and `rundev` even hands a guest
a directory of the developer's own. A Wayland compositor's endpoint is
`$XDG_RUNTIME_DIR/wayland-0`, so sharing that directory looks like the answer. It
is not: `connect()` on an `AF_UNIX` path resolves to a socket bound *in the same
kernel*. Host and guest are two kernels, so the guest finds an inode with nothing
listening behind it and gets `ECONNREFUSED`. The same reason a Unix socket on NFS
has never worked. Nothing in virtiofs proxies this, and nothing could without
being a different mechanism wearing a filesystem's name.

**Open egress does not reach the host.** A service declaring `tags: ["*"]` gets
`allow_all_egress_rule`, written on `FORWARD`. A packet addressed to one of the
host's own addresses — the guest bridge's gateway IP among them — is delivered
locally and evaluated on `INPUT`, which it never traverses. Nodo's own source says
so, in the function that exists because of this bug:

> *"Separate from `allow_connection_rule` because of the chain, and the chain is
> the whole point. […] The same allow written in FORWARD, which is what nodo wrote
> for the node's own gateway port and for the guest resolver, cannot match a single
> packet: it sits in the ruleset (and is announced in the log) as though it granted
> an access it plays no part in."*
> <sub>`src/utils/firewall/policy.py`, `allow_host_connection_rule`</sub>

And on the input side the grant is a closed list of one:

> *"The gateway is the only service of the node's own that a guest is given access
> to."*
> <sub>`src/virtualizers/microvm/network.py`</sub>

Note what this does *not* say: nodo writes no default deny on `INPUT`, so whether
a guest can reach some other host port is decided by whatever else manages that
host's ruleset. A service that dialled back to a compositor would work on a
permissive host and fail on a hardened one, for reasons no one could read in its
specification. That is not a mechanism, it is a coincidence, and building on it
would be worse than having nothing.

**There is no vsock.** `vsock` is the purpose-built host↔guest channel, waypipe
speaks it natively (`waypipe --vsock`), and it is the obvious substrate. Nodo has
none: no `CONFIG_VSOCKETS` in the guest kernel, no `--vsock` on the
cloud-hypervisor command line, no `vhost-vsock-pci` on QEMU's. A search of the
tree returns nothing.

**X11 over TCP is not the escape hatch it looks like.** X *is* network
transparent, so an X server on the host listening on TCP would be reachable if the
host's `INPUT` policy allowed it. Leave aside that it depends on the coincidence
above: X11 gives any client that connects the whole session — every keystroke to
every window, the contents of every screen, the clipboard. Handing that to a VM
whose job is to render pages from the open web is the opposite of what the VM is
for. This is the one place in this repository where Wayland is not a preference.

### The shape of the fix

**Proposal A — a host channel endpoint, which is the smaller ask.**

When a service declares it and the operator allows it, the node opens a TCP
listener on the guest bridge's gateway IP, adds one `allow_host_connection_rule`
for that VM and that port, and relays it to a Unix socket path the operator
configured. The guest connects to `<gateway ip>:<port>`, named in its
`__config__` the way the gateway already is.

What makes this small is that every piece already exists. `allow_host_connection`
is called today, in `microvm/network.py`, in the same function, for the gateway's
two ports; the rule is per-VM and per-source-IP, so the channel is not reachable
by the other guests on the bridge. No kernel change, no hypervisor argument, no
new device.

For a display the operator points it at `waypipe client`'s socket, and the guest
runs `waypipe server moonlight-qt`. Nothing in the node knows what a display is:
it opens a channel, and the two ends agree on Wayland without it.

**Proposal B — vsock, which is the cleaner one.**

`CONFIG_VSOCKETS=y` + `CONFIG_VIRTIO_VSOCKETS=y` in the guest kernel, and one
argument per hypervisor, spliced in where the virtiofs devices already are. It is
strictly better isolation: a host↔guest channel is not on the network at all, so
it cannot be confused with egress, cannot be reached from the bridge, and is not
affected by anything in the host's ruleset.

One implementation detail decides how much work it is, and it differs between the
two backends: QEMU's `vhost-vsock-pci` uses the host kernel's `vhost_vsock`, so
the host end is a real `AF_VSOCK` socket and waypipe's `--vsock` works against it
unmodified; cloud-hypervisor implements vsock in userspace and terminates it on a
host *Unix* socket with a Firecracker-style `CONNECT <port>` handshake, which
needs a small shim on the host side. Worth confirming against the version a node
actually ships before committing to it.

**A goes first.** It needs nothing of every guest, nothing of either hypervisor,
and reuses a rule the node already writes. B is where this should end up.

### What the node must enforce, either way

- **Declared in the specification.** The capability is requested in the service's
  own spec, so it is inside the content hash: a service that can reach a host
  socket must be a different service from one that cannot, and a reviewer must be
  able to see it without running anything.
- **Refusable by the operator, and off by default.** The same shape as
  `service_networks` — a node that does not want any service touching its display
  says so once in `config.yaml`, and the launch is refused before anything is
  spent, not after.
- **Never delegated.** A guest on a peer reaching *that peer's* compositor is
  meaningless at best. A service declaring this must pin to the node that granted
  it, the way a `guest` share already pins to its exporter.
- **Metered, or explicitly not.** A relayed channel costs the host bandwidth, the
  way `ServiceTunnel` does. `pricing.TUNNEL_OPEN_MU` and `NET_MU_PER_GIB` are the
  precedent; whichever way it goes, it should be a decision with a number rather
  than an omission.

---

## What is not being asked for

**A GPU.** `celaut.Sysresources` is `blkio_weight`, `cpu_period`, `cpu_quota`,
`mem_limit` and `disk_space`. There is no accelerator field, and no way to declare
that an instance needs one — the entire mention of a GPU in nodo is `nvidia-smi` in
its energy meter. A service that needs one to work cannot be scheduled anywhere on
this network, so this one is built not to: Chromium rasterises in software, and
x264 encodes on the cores the spec asks for. The ceiling that produces is real and
is stated in the README rather than argued with here.

**Sound.** The guest kernel has `# CONFIG_SOUND is not set` and that is fine.
PulseAudio's `module-null-sink` is arithmetic on a buffer — it opens no device —
and its monitor source is a capture source as far as the encoder is concerned. The
audio path needs nothing from the node, and is the one part of this service that
did not have to ask for anything.
