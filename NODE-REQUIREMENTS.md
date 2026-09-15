# What this service needs from a node, and does not have

Three things. One is two lines of kernel configuration, one is an existing
mechanism used for something it is not, and one is a distinction the specification
language cannot currently draw. Everything else in `remote-browser` runs on nodo as it ships,
which is why they are worth stating precisely rather than as a wish list.

| | what | without it | cost to the node |
|---|---|---|---|
| **1** | `CONFIG_INPUT=y` + `CONFIG_INPUT_UINPUT=y` in the guest kernel | the stream is **view-only**: you can watch a browser and not touch it | two symbols, tens of KB of `Image`, on every guest |
| **2** | a host↔guest channel that is not a network slot | the display works, over an inbound TCP slot with `socat` reversing the direction on both ends — but the viewer's display channel is then a published service API, which is not what it is | one spec field, one firewall rule the node already writes, one operator switch |
| **3** | a `Service.Network` a parent passes down without holding | a parent that launches a browser must declare open egress **for itself**, and the manifest stops describing what the instance does | one field, read in one function |

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
the screen is on the host of the node the viewer is running on.

**An earlier version of this document said there was no path from a guest to it.
That was wrong, and it was wrong in an instructive way: every mechanism it
examined was a way for the guest to *dial out* to the host, and all of those do
fail. The direction is what has to change, not the mechanism.** A guest cannot
reach the host; a guest can be reached *by* the host, on an ordinary declared
slot, which is what every other service on the network already does. The working
topology is below, under *What works today*, and it needs nothing from the node.

What is left to ask for is smaller and is about modelling rather than capability,
so the four failures are still worth walking through — they are why the obvious
direction is closed, and they are what makes the inbound shape the only one.

### Why the guest cannot dial out

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

### What works today

`waypipe` proxies the Wayland protocol over any bidirectional byte stream. Its
roles are fixed and they are the awkward part: `waypipe client` runs where the
*compositor* is and **listens**; `waypipe server` runs where the *application* is
and **dials** the client's socket. The application is in the guest, so out of the
box the guest dials — which is precisely what cannot work.

`socat` reverses it. The viewer declares one more TCP slot; the host connects in,
either to the published port or through `nodo tunnel <token> <slot> --listen`,
which needs no port published at all and authenticates with the instance token:

```
  host (your machine)                        guest (viewer microVM)
┌────────────────────────────┐             ┌──────────────────────────────┐
│ your compositor            │             │ moonlight client             │
│   ▲ unix socket            │             │   │ WAYLAND_DISPLAY          │
│ waypipe client  (listens)  │             │   ▼                          │
│   ▲ /tmp/wp-client.sock    │             │ waypipe server   (dials)     │
│ socat ─────────────────────┼── TCP ──────┼─▶ socat          (listens)   │
└────────────────────────────┘  declared   └──────────────────────────────┘
                                  slot
       host dials in ─────────────────▶   because the guest cannot dial out
```

Two `socat` processes and four hops of scaffolding, for a channel that is
conceptually one pipe. It works, and nobody should have to write it.

#### Why a window appears, which is not obvious

Nothing about a window is transported. A window *is* a sequence of messages on a
Unix socket: bind `wl_compositor` and `xdg_wm_base`, create a `wl_surface`, wrap
it in an `xdg_surface` and an `xdg_toplevel`, attach a `wl_buffer`, commit.
Anything that replays that sequence against a compositor has made a window.

What stops the socket simply being piped is that the protocol passes **file
descriptors**, as `SCM_RIGHTS` ancillary data — `wl_shm.create_pool(fd, size)`
for the pixels, `zwp_linux_buffer_params_v1.add(fd)` for a dmabuf,
`wl_keyboard.keymap(fd, size)` for the xkb keymap the compositor hands back. An
fd is an index into one process's table in **one kernel**, so copying the bytes
of the socket across leaves the far side holding a number that means nothing.
This is the same wall `AF_UNIX` over virtiofs hits, for the same reason.

So waypipe is not a tunnel, it is a translator. In the guest, `waypipe server`
offers a fake compositor socket that the application connects to. It parses only
the messages that carry an fd — everything else is forwarded opaque, which is
what makes it partly forward-compatible with protocols it has never heard of —
and for a shm pool it mmaps the region, **keeps a private copy**, and on each
commit sends only the runs that changed since the last sync, lz4 by default.

And on the host, `waypipe client` is an ordinary Wayland client of your
compositor. It creates a **local** memfd, fills it from the channel, calls
`wl_shm.create_pool` with that fd of its own, and replays the attach, the damage
and the commit. The compositor sees a normal local client with a normal toplevel:
it is in the window list, it honours the output scale, it alt-tabs. **It never
learns a VM exists.** The trick is not that Wayland was made network transparent;
it is that a local client is reconstructed on the near side. Input returns the
same way, `wl_pointer` and `wl_keyboard` events serialised back down the channel,
with the keymap fd getting the same treatment in reverse.

Which is also where the cost above comes from, stated now with the mechanism in
view. The guest kernel has `# CONFIG_DRM is not set`, so there is no `/dev/dri`,
so there is no dmabuf, so every buffer is `wl_shm` and waypipe's own video
encoding (`--video`, which needs GPU surfaces) is unavailable. What is left is
diffing and lz4-ing whole 1080p framebuffers thirty times a second. That is
waypipe doing the best available thing with shm buffers; the problem is one
decode earlier in the chain.

There is a second cost, and it is the larger one: **waypipe carries decoded
frames.** The stream arrives at the viewer as H.264, is decoded there, and is then
shipped to the host as Wayland damage — lz4-compressed, but fundamentally
uncompressed video. For a 1080p30 window that is hundreds of megabits per second
across a bridge inside one machine, to deliver pixels that crossed the network
once already, compressed, and were decoded for no other reason. On a local bridge
it is survivable. It is not defensible, and it is the honest argument for running
a Moonlight natively on the host instead — which is what this repository does
today, and why the viewer ships as a broker.

### The shape of the fix

What a node-level channel buys is therefore not *capability*. It is two things:
the scaffolding above disappears, and — the one that matters — **a display stops
being modelled as a service API.** A slot is a port a service offers to callers.
A display channel is neither offered nor called: it is one wire to one host. Every
property that follows from being a slot (published on a host port, reachable from
the bridge, tunnelled and metered as traffic) is wrong for it.

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
runs `waypipe server <client>`. Nothing in the node knows what a display is: it
opens a channel, and the two ends agree on Wayland without it. Note this still has
the guest dialling out — to a port the node opened for it specifically, which is
the difference between an address a service was given and one it went looking
for.

**Proposal B — vsock, which is the cleaner one.**

`CONFIG_VSOCKETS=y` + `CONFIG_VIRTIO_VSOCKETS=y` in the guest kernel, and one
argument per hypervisor, spliced in where the virtiofs devices already are. It is
strictly better isolation: a host↔guest channel is not on the network at all, so
it cannot be confused with egress, cannot be reached from the bridge, and is not
affected by anything in the host's ruleset.

waypipe speaks vsock natively — `waypipe --vsock -s <port> client` on the host,
`waypipe --vsock -s 2:<port> server <app>` in the guest, CID 2 being the host —
and it has since well before the 0.9.2 that Debian trixie ships. So this is the
version where the scaffolding is not replaced but deleted: no socat, no slot, no
reversal.

One implementation detail decides how much work it is, and it differs between the
two backends: QEMU's `vhost-vsock-pci` uses the host kernel's `vhost_vsock`, so
the host end is a real `AF_VSOCK` socket and waypipe's `--vsock` works against it
unmodified; cloud-hypervisor implements vsock in userspace and terminates it on a
host *Unix* socket with a Firecracker-style `CONNECT <port>` handshake, which
needs a small shim on the host side. Worth confirming against the version a node
actually ships before committing to it.

**A goes first.** It needs nothing of every guest, nothing of either hypervisor,
and reuses a rule the node already writes. B is where this should end up, and B is
the one waypipe already speaks.

**Neither is urgent**, and that is the difference between this requirement and the
first one. Requirement 1 blocks a working service: without `uinput` the stream
cannot be touched, and no amount of scaffolding in userspace changes it. This one
blocks nothing — it replaces a working ugly thing with a working clean one.

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

## 3. A grant a parent passes down without holding

`Service.Network` is authorized by intersection up the ancestor chain: a child may
use a domain only if its father declared it, and its father's father, to the top.
The AND is right, and the induction behind it is right — a father can only pass on
what it was passed. What is missing is that the same declaration does two jobs at
once, and only one of them is wanted here:

- it **grants** the domain to everything this instance launches, and
- it **takes** the domain for this instance's own VM.

There is no way to write the first without the second. So the viewer in this
repository, whose job is to hold a password and answer three HTTP routes, declares
`["*"]` — and the node duly writes `allow_all_egress_rule` for it. The manifest,
which is the thing an operator reads before admitting a launch, now says the
control plane of the session may reach the entire internet. It may. It does not.
Nothing in the specification can tell those apart.

This is not a corner case of one service. It is what happens to **every**
orchestrator with a child that talks to the world, which is most of them: the
parent is always the most privileged network declaration in its own subtree, and
it is usually the component that holds the secrets. The model inverts least
privilege exactly where it is most wanted.

### The shape of the fix

A flag on the network entry — call it `delegable_only`, `grant` versus `use`, any
name — meaning *this domain authorizes my descendants and is not opened for me*.

```json
"network": [
  { "tags": ["*"], "grant_only": true,
    "prose": "my children may reach the web; I do not" }
]
```

What changes is small and localized:

- `filter_networks_with_ancestors` keeps matching on tags exactly as it does now.
  A `grant_only` entry authorizes a descendant's request in the intersection —
  that is the whole point of it — so the walk is untouched.
- `build_network_resolution` drops `grant_only` entries from *this* instance's
  own resolution, so no `allow_all_egress_rule` and no per-destination allow is
  written for its VM.
- The operator's `service_networks` policy judges it the same way. A node that
  blacklists `*` should still refuse a service that grants `*` downward, because
  the traffic still ends up on that node's wire. Nothing about the refusal changes;
  only who gets the firewall rule does.

### Why it cannot be left to convention

Because the current failure is silent, and in the direction that hides it. A
parent that under-declares does not get an error: `filter_networks_with_ancestors`
returns `[]`, `build_network_resolution` raises nothing, and the child boots with
`block_all` and no allow rules — a browser that loads no page and reports no
problem. Every symptom points at the child.

So the pressure on an author debugging this is to widen the parent's declaration
until it works, and the widest declaration always works. The model therefore
teaches exactly the wrong habit, and does it with a symptom that never names the
file that has to change. A `grant_only` flag is the smallest thing that lets an
author widen the grant without widening the grantee — and, just as usefully, lets
the node's own error say which of the two was missing.

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
