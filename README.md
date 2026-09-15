# remote-browser

A web browser that runs on somebody else's machine, inside a microVM, and arrives
on yours — packaged as [Celaut](https://github.com/celaut-project/nodo) services,
**three of them**, which are the same browser reached three different ways.

## Why three

A browser is a good subject for *how does a service's GUI reach a person*, because
it is the **worst case** for one answer and the **best case** for another: a still
page most of the time, and full-screen motion the instant you scroll. Building one
architecture would have proved whichever point it was built to prove.

They differ in a single variable — **where the pixels are compressed, and by what**
— and everything else follows from it, including whether the thing needs anything
from the node at all.

| | input | transport | audio | needs from the node |
|---|---|---|---|---|
| [**`vnc/`**](vnc/NODE-REQUIREMENTS.md) — `Xvnc`, any VNC viewer | XTEST | RFB Tight/ZRLE | ✗ | **nothing** |
| [**`waypipe/`**](waypipe/NODE-REQUIREMENTS.md) — Chromium as a Wayland client | Wayland | damage + lz4 | ✗ | [`nodo display`](https://github.com/celaut-project/nodo/issues/367), or three commands |
| [**`stream/`**](stream/NODE-REQUIREMENTS.md) — Xvfb + Sunshine, native Moonlight | `/dev/uinput` | H.264 | ✓ | `CONFIG_INPUT` + `CONFIG_INPUT_UINPUT`, **or it is view-only** |

Read as a table it says something none of them says alone. The only one that needs
a **capability** from the node needs it for *input*, not for pixels. The only one
with **audio** is the only one that carries a real media protocol. And the one that
asks for nothing at all is the oldest technology of the three.

### Which to run

- **On your own machine or a LAN:** `waypipe/`. It has no encoder, no X server and
  no compositor — Chromium's compositor is the one on your desktop — and the cost
  is proportional to how much of the screen changes, which on a still page is
  nearly nothing.
- **Across a real network:** `stream/`. H.264 is ~1–2 MB/s whether the page is
  still or playing video, and it is the only one of the three that does not care
  what is on screen. It is also the only one you cannot yet *touch* on an
  unmodified node.
- **When you want it to work now, anywhere, with a client you already have:**
  `vnc/`. Its encodings sit between the other two by design, and it needs nothing
  from anybody.

Each directory has its own `NODE-REQUIREMENTS.md` with what it wants from the node,
what it wants from your host, and the commands to connect.

## Why this exists at all

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

## What is inside each

| | `vnc/` | `waypipe/` | `stream/` |
|---|---|---|---|
| browser | Chromium `152.0.7977.82` | Chromium | Chromium |
| display server | `Xvnc` (is also the RFB server) | **none** — waypipe is the compositor | `Xvfb` |
| encoder | RFB's own | **none** | Sunshine + x264 |
| audio | — | — | PulseAudio null sink |
| processes | 2 | 2 | 4 |

Not Chrome, in all three: Google publishes no Chrome for `linux/arm64`, so on this
architecture Chromium is not a substitution, it is the only build that exists.

Chromium runs as an unprivileged user with its own sandbox on, rather than as root
with `--no-sandbox`. The guest kernel has `CONFIG_USER_NS=y` and
`CONFIG_SECCOMP_FILTER=y`, so every layer it wants is available, and this is the
one service on the network whose job is to open pages nobody vetted. The microVM
is the boundary that matters; it is not a reason to drop the one inside it.

## What a GPU-less guest costs, which all three pay

`celaut.Sysresources` is `blkio_weight`, `cpu_period`, `cpu_quota`, `mem_limit`
and `disk_space`. There is no accelerator field, so no service on this network can
ask a node for one — and the guest kernel has `# CONFIG_DRM is not set`, so there
is no `/dev/dri` even to fall back from.

Chromium therefore rasterises every frame in software in all three. On the four
cores `at_most` asks for, the honest target is **1080p30** — text, mail, documents
and code review are fine, and video and WebGL are where the absence of a GPU stops
being an abstraction. `stream/` pays a second software cost on top, x264 on every
frame, which is what `SW_PRESET` trades against latency.

## Network

```json
"network": [{ "tags": ["*"] }]
```

The same in all three, and it is the honest form of "this is a browser". The
narrower alternative is not narrower in the way it looks: nodo resolves a domain
tag to that domain's A records **on ports 80 and 443 only**, at launch, once. A
list of domains would be a list of the sites you had thought of, pinned to the
addresses they had that afternoon — a worse description of what a browser does
than the wildcard, and one that would fail in a way nobody could read.

An operator can refuse it: `service_networks.blacklist: ["*"]` refuses every
service declaring any tagged network. The declaration exists so the refusal can be
made before the launch rather than discovered from a packet capture after it.

> Worth a footnote, because it cost a bug. An earlier two-service design had the
> parent declare `"network": []` and the child `["*"]` — and `Service.Network` is
> authorised by intersection with the ancestor chain, so the child was granted
> nothing, silently, with the launch reporting success. Three single services have
> no chain and the problem stops existing. The general fix is
> [celaut-project/nodo#365](https://github.com/celaut-project/nodo/pull/365), and
> the gap it does not close is in `NODE-REQUIREMENTS.md`.

## Reproducibility, and what it can mean here

Celaut asks that the same input give the same output, and an interactive browser
is the clearest case on this network where that cannot mean what it usually means.
The output is a session: it depends on what you click, on what the sites answered,
on the minute it ran.

What content-addressing buys is the *environment*, and that is not a consolation
prize: the base image by digest and every Debian package by its exact version, so
a security update cannot silently change which browser you ran; and, in `stream/`,
Sunshine by version **and by the sha256 GitHub publishes for that asset** — it is
not in Debian, so it arrives over the network at build time, which makes it exactly
the input that has to be nailed down.

Two people running the same digest ran the same Chromium, with the same flags, the
same fonts and the same encoder. They did not see the same pixels, and were never
going to.

## Pack

```bash
nodo pack vnc        # needs nothing from the node
nodo pack waypipe    # needs nodo display, or three commands by hand
nodo pack stream     # view-only until the guest kernel has uinput
```

`architecture` is `linux/arm64` in all three. The packer builds for the host it
runs on, so change it to match yours.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Nine, over all three services, and they check each manifest against its own
entrypoint — which is the class of bug nothing else would catch. `service.json`
declares what a node will accept and which ports it will open; `entrypoint.sh`
decides what is read and bound; nothing joins the two, so they drift in both
directions and both are silent. A variable declared and never read is one the
operator can pass to no effect — `BITRATE_KBPS` was exactly that for a while,
before anyone noticed GameStream negotiates the bitrate from the client side.

The GameStream family gets a check of its own, because it is the one set of ports
nobody writes down: Moonlight derives all eight from the `port =` base in the
generated `sunshine.conf`, so the test reads that base out of the entrypoint and
asserts the manifest declares each offset from it.

## What this is not

- **Not anonymity.** Your traffic leaves the node running the service, with that
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

Specifications and implementations. **Nothing has been packed or run.**

Every version, digest and checksum was checked against the Debian archive and the
GitHub release it names on 2026-09-15 — against `packages.debian.org` rather than
the source index, which lags behind security uploads and had quietly left this repo
pinned to a superseded Chromium.

Where to look first when each does not work:

- **`vnc/`** — whether `vncpasswd -f` is in `tigervnc-common` as assumed, and
  whether `Xvnc` is happy with `-localhost no` behind the node's DNAT.
- **`waypipe/`** — the `socat` accept order is measured and holds, but nothing has
  yet driven Chromium through a real waypipe channel. Also: whether Debian's
  Chromium is built with a working `--ozone-platform=wayland` on `arm64`.
- **`stream/`** — Sunshine's configuration keys and its `POST /api/pin` shape, both
  written from documentation; whether its X11 capture is happy with a display no
  compositor ever touched; and whether a node leaves enough of the port layout
  intact for the tunnel recipe.
