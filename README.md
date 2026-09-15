# remote-browser

A web browser that runs on somebody else's machine, inside a microVM, and arrives
on yours as a video stream — packaged as a [Celaut](https://github.com/celaut-project/nodo)
service.

## Three architectures, one question

A browser is a good subject for *how does a service's GUI reach a person*, because
it is the **worst case** for one answer and the **best case** for another: a still
page most of the time, and full-screen motion the instant you scroll. So this
repository is meant to carry three, differing in one variable — where the pixels
are compressed, and by what.

| | works today | input | transport | needs from the node |
|---|---|---|---|---|
| **1. waypipe** — Chromium as a plain Wayland client | yes | Wayland, free | damage: ~nothing still, whole framebuffer in motion | [`nodo display`](https://github.com/celaut-project/nodo/issues/367), or three commands by hand |
| **2. GameStream** — Xvfb + Sunshine, native Moonlight | **view only** | ✗ `/dev/uinput` | H.264, ~1–2 MB/s constant | `CONFIG_INPUT` + `CONFIG_INPUT_UINPUT` |
| **3. VNC** — `Xvnc`, an ordinary VNC viewer | yes | XTEST, free | Tight/ZRLE, between the two | nothing |

**`stream/` is architecture 2, and it is the only one written.** It is the one
that is cheap across a real network, and the only one that is not usable on an
unmodified node — see *Why you cannot touch it yet*. `TODO.md` has the other two.

## Why this exists

A browser is the largest attack surface most people run, and the one program they
point at code they have never read, several hundred times a day. The usual answers
are a second machine, a VM you maintain yourself, or a hosted service that watches
everything you do.

Celaut already has the parts for the first two: a node runs a service in a microVM,
on its own hardware or a peer's, and the specification says up front what it may
reach. So the useful thing to build is not a sandbox — it is a browser whose
isolation is a property of a specification anyone can read, whose engine and flags
and fonts are fixed by a content hash, and which can be handed to a machine with
cores to spare.

The stream is GameStream — [Sunshine](https://github.com/LizardByte/Sunshine)
inside the service, [Moonlight](https://moonlight-stream.org) installed natively on
your own machine — because it was built for interactive latency rather than
playback. **The client is not a celaut service and should not be**: a native
Moonlight decodes once and hands the frame to your own compositor with no copy,
which is the best possible last hop and costs nothing to arrange.

## What runs inside

| | | why this one |
|---|---|---|
| **Chromium** `150.0.7871.181` | the browser | Google publishes no Chrome for `linux/arm64`. On this architecture Chromium is not a substitution, it is the only build that exists. |
| **Xvfb** `21.1.16` | the display | The guest kernel has `# CONFIG_DRM is not set` and `# CONFIG_FB is not set`, so the framebuffer has to be one an X server allocates in ordinary memory. Xvfb also needs no VT, which is switched off too. |
| **Sunshine** `2026.914.233613` | capture, encode, protocol | `capture = x11`, and that is forced: Sunshine's Wayland capture is built on `wlr-export-dmabuf`, a dmabuf needs a DRM device, and KMS capture needs the same one. XShm is shared memory and no device, which makes it the only one of the three paths that runs on this kernel. |
| **x264** via Sunshine | the encoder | `celaut.Sysresources` has no accelerator field. A service cannot ask a node for a GPU, so an encoder that needs one cannot be scheduled anywhere on this network. |
| **PulseAudio** `17.0` | a sound card that does not exist | `# CONFIG_SOUND is not set`, but `module-null-sink` opens no device — it is arithmetic on a buffer — and its monitor is a capture source as far as the encoder cares. The only part of this service that needed nothing from the node. |

Chromium runs as an unprivileged user with its own sandbox on, rather than as root
with `--no-sandbox`. The guest kernel has `CONFIG_USER_NS=y` and
`CONFIG_SECCOMP_FILTER=y`, so every layer it wants is available, and this is the
one service on the network whose job is to open pages nobody vetted. The microVM
is the boundary that matters; it is not a reason to drop the one inside it.

## Why you cannot touch it yet

**On an unmodified node this shows you a browser and does not let you touch it.**

Sunshine injects mouse and keyboard through `/dev/uinput`, and nodo's guest kernel
is built with `# CONFIG_INPUT is not set` — switched off, per its own comment,
because a microVM has "no terminal, keyboard or physical NIC", which is true of
hardware and not of uinput. `XTestFakeKeyEvent` appears nowhere in Sunshine's
source and its packaging ships a udev rule for `/dev/uinput`, so there is no
second path to fall back to.

Two symbols, `CONFIG_INPUT=y` and `CONFIG_INPUT_UINPUT=y`; `NODE-REQUIREMENTS.md`
§1 makes the case, including the two ways to avoid asking, both of which cost a
permanent fork. Architecture 3 is the one that needs none of this.

## What it costs to encode on a CPU

Two software costs stack: Chromium rasterises every frame without a GPU, and x264
encodes every frame after it. On the four cores `at_most` asks for, at `ultrafast`
with `zerolatency`, the honest target is **1080p30** or **720p60** — not 1080p60,
and not 4K at any rate. Text, mail, documents, code review are fine. Video and
WebGL are where the absence of a GPU stops being an abstraction.

`SW_PRESET` is the knob: `ultrafast` by default because latency is what is being
bought; `veryfast` gives visibly better quality per bit and wants roughly double
the cores.

## Connecting to it

GameStream does not discover a host's ports. It **derives** them: one base, and
fixed offsets — `47989` for HTTP, base−5 for HTTPS, base+21 for RTSP, base+9 and
up for the four datagram flows. Nodo publishes each declared slot on a port taken
independently from `network.FREE_PORTS_RANGE`, so the offsets between them are
whatever its allocator had free, and a Moonlight pointed at the published HTTP
port computes four wrong ports for everything else.

Rebuild the family locally instead, one tunnel per slot, each pinned to the port
Moonlight expects:

```bash
for p in 47989 47984 47990 48010; do nodo tunnel <instance> $p --listen $p & done
for p in 47998 47999 48000 48002; do nodo tunnel <instance> $p --listen $p --udp & done
```

Then point Moonlight at `127.0.0.1`, take the PIN it shows you, and enter it in
Sunshine's web UI on `https://127.0.0.1:47990` with the credentials you launched
with.

**One honest caveat about the UDP tunnels.** `TUNNELING.md` is explicit that
datagrams through the tunnel become reliable and can head-of-line block, which for
a video stream is precisely the property UDP was chosen to get. Against a node on
your own machine that is a non-issue — there is no real link to lose packets on.
Against a remote node it is a real cost, and the alternative is direct exposure,
which gives back the offsets problem. That tension is not resolved here.

## The environment it reads

| variable | | what it is |
|---|---|---|
| `ADMIN_USER` / `ADMIN_PASS` | **required** | Sunshine's configuration API. The service refuses to start without them rather than generating one: an unset password leaves port 47990 open to every other guest on the bridge, and a generated one would have to be read back out of the serial log. |
| `START_URL` | `about:blank` | The page the session opens on. |
| `WIDTH` / `HEIGHT` | `1920` / `1080` | Both must be even — H.264 chroma subsampling. |
| `FPS` | `30` | See *What it costs to encode on a CPU* before raising it. |
| `SW_PRESET` | `ultrafast` | An x264 preset. The latency/quality/cores knob. |
| `LOCALE` | `en-US` | Chromium's `--lang`. |
| `TIMEZONE` | `UTC` | The container's `TZ`. A browser reports it, so the default is the private choice and setting it is the convenient one. |

## Resources and network

| | `at_init` | `at_most` |
|---|---|---|
| memory | 2 GB | 6 GB |
| disk | 6 GB | 12 GB |
| CPU | 2 cores | 4 cores |

```json
"network": [{ "tags": ["*"] }]
```

Open egress is the honest form of "this is a browser". The narrower alternative is
not narrower in the way it looks: nodo resolves a domain tag to that domain's A
records **on ports 80 and 443 only**, at launch, once. A list of domains would be
a list of the sites you had thought of, pinned to the addresses they had that
afternoon — a worse description of what a browser does than the wildcard, and one
that would fail in a way nobody could read.

An operator can refuse it: `service_networks.blacklist: ["*"]` refuses every
service declaring any tagged network. The declaration exists so the refusal can be
made before the launch rather than discovered from a packet capture after it.

> Worth a footnote, because it cost a bug. When this was two services, the parent
> declared `"network": []` and the child `["*"]` — and `Service.Network` is
> authorized by intersection with the ancestor chain, so the child was granted
> nothing, silently, with the launch reporting success. One service has no chain
> and the problem stops existing. The general fix is
> [celaut-project/nodo#365](https://github.com/celaut-project/nodo/pull/365).

## Reproducibility, and what it can mean here

Celaut asks that the same input give the same output, and an interactive browser
is the clearest case on this network where that cannot mean what it usually means.
The output is a session: it depends on what you click, on what the sites answered,
on the minute it ran.

What content-addressing buys here is the *environment*, and that is not a
consolation prize: the base image by digest and every Debian package by its exact
version, so a security update cannot silently change which browser you ran; and
Sunshine by version **and by the sha256 GitHub publishes for that asset** — it is
not in Debian, so it arrives over the network at build time, which makes it exactly
the input that has to be nailed down.

Two people running the same digest ran the same Chromium, with the same flags, the
same fonts, the same encoder and the same preset. They did not see the same pixels,
and were never going to.

## Pack

```bash
nodo pack stream
```

`architecture` is `linux/arm64`. The packer builds for the host it runs on, so
change it to match yours.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Five, and they check the manifest against the entrypoint — which is the only class
of bug left that nothing else would catch. `service.json` declares what a node will
accept at `nodo execute -e`; `entrypoint.sh` decides what it reads; nothing joins
the two, so they drift in both directions and both are silent. A variable declared
and never read is one the operator can pass to no effect — `BITRATE_KBPS` was
exactly that for a while, before anyone noticed GameStream negotiates the bitrate
from the client side.

## What this is not

- **Not anonymity.** Your traffic leaves the node running this service, with that
  node's address. If the balancer delegated it to a peer, it leaves from the peer
  — browsing on someone else's connection is a thing to decide deliberately, not
  to discover.
- **Not confidential from the node.** Whoever operates the machine running it can
  read the page: it is rendered in their RAM. Celaut's isolation is between
  *services*; what is between you and an operator is their reputation.
- **Not a persistent profile.** The profile lives in the service's own disk, which
  ends when the instance does. That is the right default here, and it means your
  logins do not survive a session.

## Status

Specification and implementation, neither packed nor run.

Every version, digest and checksum in the Dockerfile was checked against the
Debian archive and the GitHub release it names, on 2026-09-15. Three things are
written from documentation rather than from a running system, and are where to
look first when it does not work: Sunshine's configuration keys, whether its X11
capture is happy with a display no compositor ever touched, and whether a node
leaves enough of the port layout intact for the tunnel recipe above.
