# TODO

## The display path — deferred on purpose

The viewer can put a real window on your desktop today, with nothing added to the
node. It is not wired up, and the reason is a judgement rather than a missing
afternoon: **waypipe carries decoded frames.** The stream would arrive at the
viewer as H.264, be decoded there, and cross a bridge inside one machine as
uncompressed Wayland damage — hundreds of megabits per second to deliver pixels
that already crossed the network once, compressed. A Moonlight running natively
on the host does the same job with one decode and no second transport, which is
why the viewer ships as a broker.

Noted here in full so that whoever picks it up does not have to re-derive it.
`NODE-REQUIREMENTS.md` §2 has the mechanism, including why a window appears at
all.

### What it would take

- **A second slot on the viewer**, TCP, declaring `"protocol": ["waypipe"]` so
  that a client can find it by what it speaks rather than by a port number the
  user has to be told. TCP because waypipe's channel is one long-lived
  bidirectional stream with its own framing and ordering; a celaut UDP slot
  carries one datagram per beeRPC message and has no connection, which is the
  wrong shape. Reached either from the published port or — better — through
  `nodo tunnel <token> <slot> --listen`, which publishes nothing and
  authenticates with the instance token.
- **`waypipe` and `socat`** in the viewer image. Both are in Debian trixie
  (`0.9.2-1` and `1.8.0.3-1+deb13u1`), so both pin like everything else.
- **One `socat` at each end, to reverse the direction.** waypipe's roles are fixed
  the wrong way round for this: `client` runs where the compositor is and
  **listens**, `server` runs where the application is and **dials**. The guest
  cannot dial the host, so the host dials in and `socat` splices. What listens on
  the slot is therefore not waypipe.

  ```
  socat TCP-LISTEN:<slot>,reuseaddr UNIX-LISTEN:/run/waypipe.sock
  ```

  The ordering that falls out of this is favourable, and it was measured rather
  than assumed: socat accepts on its **first** address and only then creates and
  accepts on the second, so the slot listens from boot while
  `/run/waypipe.sock` appears exactly when a session begins. The service waits
  for that socket and then launches `waypipe server <client>` — which is both the
  natural shape and the correct one, and it means there is no window in which
  `waypipe server` can dial a socket that is not there yet. Verified end to end,
  both directions, with socat 1.8.
- **A Moonlight client built from source.** This is the unpleasant part.
  Moonlight is packaged for Linux `arm64` nowhere: not in Debian, and upstream
  ships only an `x86_64` AppImage (`MoonlightPortable-arm64` is a Windows build).
  The clean route is `moonlight-embedded` from a source tarball pinned by
  sha256 — it is C, links SDL2, ffmpeg and opus, all of which are in Debian, and
  its `sdl` platform decodes in software and renders through SDL2's Wayland
  backend, which is exactly what waypipe wants.
- **Revisit the viewer's resources.** It is declared at 256 MB / 1 core
  `at_init` and 768 MB / 2 cores `at_most`, sized for a broker. Software H.264
  decode of 1080p30 plus waypipe's diffing is not that, and the numbers in
  `.service/service.json` and the README table have to move together.
- **A host-side runbook**, three commands: `waypipe client`, `nodo tunnel`,
  `socat`. It belongs in the README, not in a script, because it runs on the
  user's machine and not in any service — and it is exactly the three commands
  that [celaut-project/nodo#367](https://github.com/celaut-project/nodo/issues/367)
  proposes collapsing into `nodo display`.

### What would make most of it unnecessary

`NODE-REQUIREMENTS.md` §2, proposal B — a vsock device on the guest. waypipe
speaks vsock natively and has since well before the 0.9.2 Debian ships, so the
two `socat` processes, the extra slot and the direction reversal all disappear:
`waypipe --vsock -s <port> client` on the host, `waypipe --vsock -s 2:<port>
server <client>` in the guest. The redundant decode does not disappear, and it is
the larger cost, so this changes the plumbing and not the judgement above.

## Two architectures worth considering instead

Both would replace what is here rather than extend it, and both are measured
against a baseline that is easy to forget: **a native Moonlight on the host.**
Zero node changes, one decode, and the last hop is already zero-copy because the
user's own compositor does it. That works today. Anything below has to buy
something over that.

### A. One service, waypipe, no streaming layer

Drop Moonlight and Sunshine. The service runs Chromium as a plain Wayland client
of `waypipe server` and declares one waypipe slot;
[`nodo display`](https://github.com/celaut-project/nodo/issues/367) connects to
it.

What disappears, all at once: the viewer service, Sunshine, Xvfb, any compositor
in the guest (waypipe *is* the compositor as far as Chromium is concerned), the
encoder, `/dev/uinput` and therefore requirement 1 entirely, the PIN pairing, the
administrator credentials, `possible_environment_workload`, the GameStream port
offsets, and the parent/child network inheritance. One service, one slot, one
command.

**Where it stops, and it is specific to browsers.** Damage tracking wins when the
screen is still, and what one does in a browser is *scroll*, which is full-screen
damage. So the cost is not low, it is **bursty** — and the bursts land exactly on
the moments of interaction, which are the moments latency is noticed.

| | damage per frame at 1080p |
|---|---|
| still page, cursor blinking | hundreds of bytes |
| scrolling text | whole screen, but lz4 does well on text (3–5×) → ~2 MB |
| video, GIF, carousel, CSS animation | the worst case, ~8.3 MB |

H.264 is the mirror image: ~1–2 MB/s constantly. Worse at rest, far better in
motion.

**And the part that only shows up in the bill.** If the service runs on a peer and
the channel is tunnelled, `pricing.NET_MU_PER_GIB` meters it. At damage rates that
is on the order of 360 GB/hour against 3.6 GB/hour for H.264 at 8 Mbps — two
orders of magnitude. Directly exposed rather than tunnelled it is not metered
(*"Only what crosses this relay is counted"*), so it depends on the deployment.

**Verdict:** excellent on the same machine or a LAN. Doubtful across a real
network, which is the case that motivated this service.

### B. Zero-copy on the last hop, via virtio-gpu

The right architecture for the remote case, and what every serious remote-desktop
client does: decode into a GPU surface the compositor scans out without copying.

**The thing to get right about it:** a parent that shares memory with the host
does not solve the child's pixels. virtio-gpu shares memory **guest↔host**, never
guest↔guest, so the child's frames still have to cross a VM boundary and the only
answer is a compressed stream. Sunshine and Moonlight stay in the design. What
DRM buys is the *final* hop — which is the expensive one in option A, so this is
not a small thing; it just is not a replacement for the streaming layer.

**It is not a matter of `architecture`.** That field is CPU ISA and nothing else:
`ARCH_ALIASES` collapses every spelling into `linux/amd64` or `linux/arm64`, and
`normalize_arch_tag` returns `None` for anything outside the table. Declaring
"kernel with DRM" there would break the only vocabulary the scheduler has. It is a
**capability request** — the same shape as the display channel in
`NODE-REQUIREMENTS.md` §2 and the grant-only network flag in §3.

**And it is much more than `CONFIG_DRM`.** It needs `CONFIG_DRM_VIRTIO_GPU`, a
virtio-gpu device per VM on the hypervisor command line, **blob resources**
(`VIRTIO_GPU_F_RESOURCE_BLOB`) which is the mechanism that actually exports guest
memory as a host dmabuf, a display backend on the host, and a host-side Wayland
client importing it through `zwp_linux_dmabuf_v1`. That is roughly what
`crosvm --gpu` does.

Two structural consequences on top: nodo has **one kernel per architecture**
(`virtualizers.ch.KERNEL_PATHS`, keyed by arch), so a DRM variant adds a dimension
to scheduling; and the kernel is **not part of a service's content hash**, so
"same digest, different kernel" is a determinism question that needs an answer
before it is a feature.

**One gap neither of these has today:** nothing lets a service declare *"run me on
the node of whoever asked for me"*. Shares force colocation with a **parent**;
nothing forces colocation with the **requester**. Option B's parent needs exactly
that, and currently only gets it by accident, as long as `DELEGATE_EXECUTION`
happens not to send it away.

## Not blocked on us

- **Input.** The stream is view-only on an unmodified node: Sunshine injects
  through `/dev/uinput` and nodo's guest kernel is built with
  `# CONFIG_INPUT is not set`. `NODE-REQUIREMENTS.md` §1 — two symbols, and the
  two ways to avoid asking for them, both of which cost a permanent fork.

## Verification

Nothing in this repository has been packed or run. In rough order of how likely
each is to be what breaks first:

- `nodo pack browser` then `nodo pack .`, and an instance of each.
- **Sunshine's X11 capture against a display no compositor ever touched.** Xvfb
  with no window manager is not a configuration Sunshine is routinely tested on.
- **The `sunshine.conf` keys** in `browser/service/entrypoint.sh`, written from
  Sunshine's documentation rather than from a running instance.
- **The `POST /api/pin` request shape** in `service/sunshine.py`. `pairing_id` is
  sent only when a caller supplies one, because older Sunshine takes the PIN
  alone; which of the two this build wants is untested.
- Whether the node leaves GameStream's port offsets intact on a real launch.
  `GET /session` reports it, and `Child.offsets_survived` has tests, but neither
  has met an actual allocator.
