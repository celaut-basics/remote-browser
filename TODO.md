# TODO

All three architectures are written. The list below is in three parts now: what has
been *confirmed* against running images, what is still to be *confirmed*, and what
is genuinely *left to build*.

## Confirmed, 2026-09-15

All three images built for `linux/arm64` and were run. Six things were wrong, and
five of them stopped the service dead — none of which a reading would have caught,
which is the argument for having done this at all.

### What was broken

1. **No sandbox, in all three.** `chromium-sandbox` is a *Recommends* of `chromium`
   and every image installs with `--no-install-recommends`, so the setuid helper was
   in none of them. Chromium does not warn and carry on: `No usable sandbox!` and
   **exit 1**, before a window. Every one of these three was a browser that could not
   start, and the README's paragraph about keeping the sandbox on was describing an
   image that did not have one. Named explicitly now, in all three.
2. **`vncpasswd` is not in `tigervnc-common`.** TODO asked; the answer is no. That
   package ships exactly one binary, `tigervncconfig`. `vncpasswd` is in
   **`tigervnc-tools`** — as `tigervncpasswd`, reached through alternatives. The
   entrypoint's first real command was `vncpasswd -f`, so `vnc/` died on line one.
3. **`pulseaudio=17.0+dfsg1-2` does not exist on `arm64`.** It is `17.0+dfsg1-2+b1`
   there: a binNMU, a rebuild carrying a binary-only suffix on the architectures it
   was rebuilt for. The archive shows the source version, so this is the one pin that
   cannot be checked against `packages.debian.org` at all. `stream/` failed in apt.
   Every other pin in all three images is identical on both architectures.
4. **`/etc/sunshine/` does not exist.** The Sunshine `.deb` ships a binary, a udev
   rule and a systemd user unit, and no `/etc` directory — it writes its config next
   to its state on first run, as a desktop user. The entrypoint's heredoc therefore
   failed under `set -e`, as PID 1, *after* Xvfb and PulseAudio had already logged
   healthy. `mkdir -p /etc/sunshine` now.
5. **`fps` and `resolutions` are not Sunshine configuration keys.** Sunshine says so
   itself: `Warning: Unrecognized configurable option [resolutions]`, same for `fps`,
   and then it starts normally. Both are gone. `FPS` went with them — it had no other
   consumer, exactly as `BITRATE_KBPS` did, and for the same underlying reason:
   GameStream negotiates resolution and frame rate from the client. The other fourteen
   keys are valid, checked against `src/config.cpp` at the pinned tag.
6. **`COPY service /service` breaks `nodo pack` while building fine under `docker
   build`.** The packer sets the context to `.service/` and stages the project under
   `service/` within it, rewriting COPY origins that begin with `.` — and leaving bare
   relative origins alone. So the same line means two different paths, and only the
   docker one existed. `./service` now, in all three, with a test that fails if any of
   them loses the dot again.

### What was confirmed working

- **`vnc/`, end to end, and the claim the architecture rests on.** Xvnc and Chromium
  come up, a viewer authenticates with VncAuth and gets a real 1280×800 framebuffer
  with a rendered page and working fonts. **Input lands**: five `Page_Down` keys sent
  over RFB moved 12.4% of the framebuffer on a long text page, with the scrollbar
  where it should be. XTEST, no `/dev/uinput`, on a stock kernel — as claimed.
- **`-AlwaysShared` and reconnect.** Three sequential sessions reconnected to a live
  instance, and two simultaneous clients both got frames with neither displacing the
  other. Browser state survived all of it. A wrong password is refused.
- **`Xvnc` takes `-localhost no`, `-AlwaysShared`, `-rfbauth`, `-SecurityTypes`,
  `-desktop`** — read out of its own usage output, not assumed.
- **`waypipe/`: Chromium really is a Wayland client on `arm64`.** It ran under
  `--ozone-platform=wayland` through a real channel — `waypipe server`, the `socat`
  reversal, `waypipe client`, a compositor at the far end — and loaded pages. No
  Xwayland. The service-side accept order behaves exactly as the entrypoint's comment
  says: the slot listens from boot, and the channel appears when the host dials in.
- **What scrolling costs, measured.** See `waypipe/NODE-REQUIREMENTS.md`. Idle is
  **zero** bytes, not "hundreds"; scrolling text compresses **12.8×**, not 3–5×, so
  the per-frame figure is ~0.65 MB at 1080p rather than ~2 MB. The estimate was
  pessimistic by about three times. The verdict it supports does not change.
- **`stream/`: Sunshine captures a WM-less Xvfb.** No black screen and no horizontal
  lines. `Screencasting with X11`, `Found H.264 encoder: libx264 [software]`, and the
  display holds a mapped Chromium window with a rendered page on it — dumped straight
  off the root window to check. All four processes stay up; 47989 answers HTTP and
  47990 answers HTTPS.
- **The `POST /api/pin` shape**, read off this build's `confighttp.cpp` and confirmed
  against a running instance. `pairing_id` **is** required, 32 hex characters, and it
  comes from the `GET` — so the POST answers a pairing request and cannot open one.
  The whole shape, and the three other things it enforces, are now in
  `stream/NODE-REQUIREMENTS.md`.
- **The Sunshine asset checksum.** `SUNSHINE_SHA256` in the Dockerfile matches the
  digest GitHub publishes for that asset, exactly.

## Confirm, in this order

What is left is the part that needs a node, rather than an image.

1. **`nodo pack`, on all three.** The context bug above was found by running the
   packer and is fixed; the packs have not yet been carried through to a service id.
   Note that `nodo pack` no longer builds locally by default — it wants a
   packer-service id in `core_services.packer`, or `packer.local: true` to use its own
   isolated toolchain. The local path also shells out to `unzip` without depending on
   it, which is worth an issue upstream.
2. **Launch, and `nodo tunnel <instance> 5900 --listen 5900`.** Everything above was
   reached over a container network standing in for the tunnel; the byte path is the
   same, the DNAT is not. Whether `Xvnc -localhost no` is reachable through the node's
   DNAT specifically is still open.
3. **Whether a node leaves enough of the port layout intact for the eight-tunnel
   recipe** in `stream/NODE-REQUIREMENTS.md`.
4. **A real Moonlight against `stream/`.** Capture, encoder and pairing API are
   confirmed; an actual paired session, and the audio the null sink is supposed to
   carry, are not. There is no Moonlight for Linux `arm64`, which is why this one
   needs a host.
5. **waypipe's worst case.** Video and CSS animation were not measured, only idle and
   scrolling text.

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
