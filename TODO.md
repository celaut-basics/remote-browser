# TODO

All three architectures are written. Nothing has been packed or run, so the list
below is in two halves: what has to be *confirmed*, and what is genuinely *left to
build*.

## Confirm, in this order

Each of these is a thing written from documentation rather than from a running
system, ordered by how likely it is to be what breaks first.

### `vnc/` — the one that should work

1. `nodo pack vnc`, launch, `nodo tunnel <instance> 5900 --listen 5900`, point any
   viewer at `127.0.0.1:5900`.
2. Whether `vncpasswd` ships in `tigervnc-common`. If not, the password file is
   eight DES-obfuscated bytes and can be written without it, but the entrypoint
   currently assumes the tool.
3. Whether `Xvnc -localhost no` is reachable through the node's DNAT, and whether
   `-AlwaysShared` behaves on reconnect.
4. **Input, end to end.** This is the claim the whole architecture rests on: XTEST
   needs no `/dev/uinput`, so a click should arrive where `stream/` cannot make one
   arrive at all.

### `waypipe/` — the one with a moving part

1. The host side: `waypipe client`, `nodo tunnel`, `socat`. The service side's
   `socat` accept order is measured and holds; nothing has yet driven Chromium
   through a real channel.
2. Whether Debian's Chromium on `arm64` has a working `--ozone-platform=wayland`.
   If not, the fallback is Xwayland, which would put an X server back into the one
   architecture that does not have one.
3. What scrolling actually costs. The estimate is ~2 MB a frame for text after
   lz4; it is an estimate.

### `stream/` — the one that is view-only

1. **Sunshine's X11 capture against a display no compositor ever touched.** Xvfb
   with no window manager is not a configuration Sunshine is routinely tested on,
   and a known class of bug there is a black screen with horizontal lines rather
   than an error.
2. The `sunshine.conf` keys, written from Sunshine's documentation.
3. The `POST /api/pin` request shape, and whether this build wants `pairing_id`.
4. Whether a node leaves enough of the port layout intact for the eight-tunnel
   recipe in `stream/NODE-REQUIREMENTS.md`.

## Build

### Session lifetime in `waypipe/`

One session per instance today: `waypipe server` launches Chromium, and when the
channel closes both die. waypipe has a `recon` subcommand for reattaching a server
to a new socket, which would let the browser — and your tabs — outlive a
disconnection. Worth doing, and deliberately not guessed at in the first version.

### The port layout in `stream/`, which has no good answer yet

Moonlight derives every port from one base by fixed offsets; nodo publishes each
slot on an independently chosen free port. The eight-tunnel recipe rebuilds the
family locally and works, but it puts the four media flows through a relay that
makes datagrams reliable and can head-of-line block — fine against a node on your
own machine, a real cost against a remote one. Direct exposure gives the offsets
problem back. Neither is right and there is no third option today.

### Audio in `vnc/` and `waypipe/`

Neither has any. RFB carries none and Wayland carries none, so in both cases it
would be a second channel of its own. `stream/` gets it free because GameStream is
a media protocol. Whether a second slot carrying PulseAudio is worth it is an open
question, not a plan.

## Not blocked on us

- **`uinput`**, for `stream/` only, and without it that architecture is view-only.
  [`stream/NODE-REQUIREMENTS.md`](stream/NODE-REQUIREMENTS.md) makes the case. Two
  symbols. Worth its own issue, and the argument is better without a display in
  it: the services with the strongest claim on uinput display nothing at all.
- **`nodo display`**, for `waypipe/` only, and it is a convenience rather than a
  capability — the three commands work.
  [celaut-project/nodo#367](https://github.com/celaut-project/nodo/issues/367).

## Considered and dropped

**A guest kernel with virtio-gpu.** Blob resources (`VIRTIO_GPU_F_RESOURCE_BLOB`)
export guest memory as a host dmabuf, which would make the last hop zero-copy. Its
only purpose was to let the *client* be a celaut service — and a natively installed
client already gets a zero-copy last hop from the user's own compositor, for free.
It would have cost `CONFIG_DRM_VIRTIO_GPU`, a device per VM, a host display
backend, a dmabuf-importing Wayland client, a second guest kernel per architecture
(nodo keys `virtualizers.ch.KERNEL_PATHS` by architecture alone) and an answer to
*same digest, different kernel*, all for a want that turned out not to exist.

**A viewer service.** The two-service design this repository started as: a light
parent that decoded the stream and a heavy child that produced it. It died on
arithmetic — waypipe carries decoded frames, so the parent would have decoded H.264
and re-shipped the result as uncompressed Wayland damage across a bridge inside one
machine, to deliver pixels that had already crossed the network compressed. A
natively installed Moonlight does the same job with one decode and no second
transport.

Two findings outlived both, and they are in
[`NODE-REQUIREMENTS.md`](NODE-REQUIREMENTS.md): `architecture` could not have
carried a kernel-capability request, and nothing lets a service ask to run on the
node of whoever requested it.
