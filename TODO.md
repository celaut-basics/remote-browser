# TODO

## What this repository is for

A browser in a microVM is a useful subject for the question *how does a service's
GUI reach a person*, because it is the **worst case** for one answer and the
**best case** for another: a browser is a still page most of the time and
full-screen motion the instant you scroll.

So this repository carries **three architectures** rather than picking one. They
differ in one variable — where the pixels are compressed, and by what — and
everything else follows from it, including whether the thing needs anything from
the node at all.

| | works today | input | transport | needs from the node |
|---|---|---|---|---|
| **1. waypipe** | **yes** | Wayland, free | damage: ~nothing still, whole framebuffer in motion | [`nodo display`](https://github.com/celaut-project/nodo/issues/367), or three commands by hand |
| **2. GameStream** | **view only** | ✗ `/dev/uinput` | H.264, ~1–2 MB/s constant | `CONFIG_INPUT` + `CONFIG_INPUT_UINPUT` |
| **3. VNC** | **yes** | XTEST, free | Tight/ZRLE, between the two | **nothing** |

Architecture 2 is what `stream/` holds today. 1 and 3 are not
written yet.

---

## 1. Chromium as a plain Wayland client, over waypipe

One service. Chromium runs as an ordinary Wayland client of `waypipe server`, and
[`nodo display`](https://github.com/celaut-project/nodo/issues/367) connects to it
— or, until that exists, three commands by hand.

What is *not* in this architecture, all at once: any X server, any compositor in
the guest (waypipe **is** the compositor as far as Chromium is concerned), the
video encoder, `/dev/uinput`, the PIN pairing, the administrator credentials, a
second service, `possible_environment_workload`, and the GameStream port offsets.

**Where it stops, and it is specific to browsers.** Damage tracking wins when the
screen is still, and what one does in a browser is *scroll*, which is full-screen
damage. The cost is **bursty**, and the bursts land on the moments of interaction
— which are the moments latency is noticed.

| | damage per frame at 1080p |
|---|---|
| still page, cursor blinking | hundreds of bytes |
| scrolling text | whole screen, but lz4 does well on text (3–5×) → ~2 MB |
| video, GIF, carousel, CSS animation | the worst case, ~8.3 MB |

There is no help available for the last row: the guest kernel has
`# CONFIG_DRM is not set`, so every buffer is `wl_shm`, and waypipe's own
`--video` is documented as *"Compress specific DMABUF formats using a lossy video
codec"* — it does not apply.

**And the part that only shows up in the bill.** Tunnelled, `pricing.NET_MU_PER_GIB`
meters this: damage rates run on the order of 360 GB/hour against 3.6 GB/hour for
H.264 at 8 Mbps. Directly exposed rather than tunnelled it is not metered
(*"Only what crosses this relay is counted"*), so it depends on the deployment.

### What it would take

- `waypipe` and `socat` in the image — both in Debian trixie (`0.9.2-1`,
  `1.8.0.3-1+deb13u1`), so both pin like everything else.
- **One TCP slot** declaring `"protocol": ["waypipe"]`, so a client finds it by
  what it speaks rather than by a port number someone has to be told. TCP because
  waypipe's channel is one long-lived stream; a celaut UDP slot carries one
  datagram per beeRPC message and has no connection.
- **One `socat` at each end, to reverse the direction.** `waypipe client` listens
  where the compositor is; `waypipe server` dials from where the application is.
  The guest cannot dial the host, so the host dials in:

  ```
  socat TCP-LISTEN:<slot>,reuseaddr UNIX-LISTEN:/run/waypipe.sock
  ```

  The ordering that falls out is favourable, and it was measured rather than
  assumed: socat accepts on its **first** address and only then creates and
  accepts on the second. So the slot listens from boot while
  `/run/waypipe.sock` appears exactly when a session begins — the service waits
  for that socket and then launches `waypipe server chromium`, and there is no
  window in which it can dial a socket that is not there. Verified end to end,
  both directions, socat 1.8.
- A host-side runbook of three commands: `waypipe client`, `nodo tunnel`,
  `socat` — which is exactly what
  [nodo#367](https://github.com/celaut-project/nodo/issues/367) proposes
  collapsing into one.

---

## 2. Xvfb + Sunshine, with a native Moonlight (built today)

H.264 is the only one of the three that is cheap across a real network, and
constant rather than bursty. It is what `stream/` implements.

**It is view-only on an unmodified node**, and that is not a detail: Sunshine's
only input backend is `/dev/uinput`. `XTestFakeKeyEvent` appears nowhere in its
source, and its packaging ships a udev rule for `/dev/uinput`, which is what a
hard dependency looks like. The guest kernel is built with
`# CONFIG_INPUT is not set`. See `NODE-REQUIREMENTS.md` §1 — two symbols.

The viewer service is **gone**, and with it `child.py`, `sunshine.py`, the PIN
broker, the generated credentials, `possible_environment_workload` and the
parent/child network inheritance. Pairing now happens the ordinary way: `nodo
tunnel` to slot 47990 and Sunshine's own web UI, with the administrator password
passed at `nodo execute -e`.

### Pending here

- **The port layout, which got harder rather than easier.** The viewer solved it
  by being a sibling on the same bridge and dialling the child's guest IP at
  canonical ports. A native Moonlight cannot do that: it must reach whatever ports
  the node published, and GameStream derives every port from one base by fixed
  offsets. The README's recipe rebuilds the family with one
  `nodo tunnel --listen` per slot, which works but puts the four media flows
  through a relay that makes datagrams reliable and can head-of-line block. Fine
  against a node on your own machine, a real cost against a remote one, and direct
  exposure gives the offsets problem back. Unresolved.
- Note for anyone tempted to put Moonlight *in* an image: it is packaged for Linux
  `arm64` nowhere. Not in Debian, and upstream ships only an `x86_64` AppImage
  (`MoonlightPortable-arm64` is a Windows build). On the **host** it installs
  normally, which is the whole point of this architecture.

---

## 3. Xvnc and an ordinary VNC viewer

The one that needs nothing from anybody, and the answer that was in plain view the
whole time: **VNC servers inject input through XTEST** — pure userspace, no kernel
input subsystem — and have for twenty-five years.

With TigerVNC there is not even an Xvfb: `Xvnc` is the X server and the VNC server
in one process, so the service is two processes and a slot. Both
`tigervnc 1.15.0+dfsg-2.1~deb13u1` and `x11vnc 0.9.17-1` are in Debian trixie.

A VNC server **listens**, so it fits a celaut slot natively and `nodo tunnel` plus
any ordinary viewer already reaches it. Nothing to add to the node, nothing to
reverse, no command that does not exist yet.

Its encodings (Tight, ZRLE) are built for desktop content, which puts it between
the other two on purpose: far better than raw damage on a still screen, clearly
worse than H.264 in motion, latency worse than Moonlight and fine for browsing.

### Pending here

All of it. Nothing of architecture 3 is written.

---

## Considered and dropped

**A guest kernel with virtio-gpu.** Blob resources (`VIRTIO_GPU_F_RESOURCE_BLOB`)
export guest memory as a host dmabuf, which would make the last hop zero-copy. Its
only purpose was to let the *client* be a celaut service — and a natively
installed client already gets a zero-copy last hop from the user's own compositor,
for free. It would have cost `CONFIG_DRM_VIRTIO_GPU`, a device per VM, a host
display backend, a dmabuf-importing Wayland client, a second guest kernel per
architecture (nodo keys `virtualizers.ch.KERNEL_PATHS` by architecture alone) and
an answer to *same digest, different kernel*, all for a want that turned out not to
exist.

Two notes kept from working it out, because they are true beyond this repository:

- It would not have been a matter of `architecture`. That field is CPU ISA and
  nothing else — `ARCH_ALIASES` collapses every spelling into `linux/amd64` or
  `linux/arm64`, and `normalize_arch_tag` returns `None` for anything outside the
  table. It would have been a capability request.
- Nothing lets a service declare *"run me on the node of whoever asked for me"*.
  Shares force colocation with a **parent**; nothing forces colocation with the
  **requester**. Any design where a light local service faces the user needs
  exactly that, and today only gets it by accident, as long as
  `DELEGATE_EXECUTION` happens not to send it away.

---

## Not blocked on us

- **`uinput`**, for architecture 2 only. `NODE-REQUIREMENTS.md` §1 — two symbols,
  and the two ways to avoid asking for them, both of which cost a permanent fork.
  Worth its own issue, and the argument is better without a display in it: the
  services with the strongest claim on uinput display nothing at all.
- **`nodo display`**, for architecture 1 only.
  [nodo#367](https://github.com/celaut-project/nodo/issues/367).

---

## Verification

Nothing in this repository has been packed or run. In rough order of how likely
each is to be what breaks first:

- `nodo pack browser` then `nodo pack .`, and an instance of each.
- **Sunshine's X11 capture against a display no compositor ever touched.** Xvfb
  with no window manager is not a configuration Sunshine is routinely tested on.
- **The `sunshine.conf` keys** in `stream/service/entrypoint.sh`, written from
  Sunshine's documentation rather than from a running instance.
- **Whether the tunnel recipe in the README actually carries a session**, which
  is the one thing the viewer used to make unnecessary.
