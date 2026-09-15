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

- **A second slot on the viewer**, TCP, for the waypipe channel. Reached either
  from the published port or — better — through `nodo tunnel <token> <slot>
  --listen`, which publishes nothing and authenticates with the instance token.
- **`waypipe` and `socat`** in the viewer image. Both are in Debian trixie
  (`0.9.2-1` and `1.8.0.3-1+deb13u1`), so both pin like everything else.
- **Two `socat` processes, to reverse the direction.** waypipe's roles are fixed
  the wrong way round for this: `client` runs where the compositor is and
  listens, `server` runs where the application is and dials. The guest cannot
  dial the host, so the host dials in and `socat` splices at both ends.
- **An ordering constraint that needs care.** `waypipe server` connects to its
  socket rather than listening on it, so the guest side cannot start the client
  before the host's connection has arrived. Starting `waypipe server <client>` on
  demand — when the channel opens — is the natural shape, and it is also the
  right one: a session begins when somebody connects.
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
  user's machine and not in any service.

### What would make most of it unnecessary

`NODE-REQUIREMENTS.md` §2, proposal B — a vsock device on the guest. waypipe
speaks vsock natively and has since well before the 0.9.2 Debian ships, so the
two `socat` processes, the extra slot and the direction reversal all disappear:
`waypipe --vsock -s <port> client` on the host, `waypipe --vsock -s 2:<port>
server <client>` in the guest. The redundant decode does not disappear, and it is
the larger cost, so this changes the plumbing and not the judgement above.

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
