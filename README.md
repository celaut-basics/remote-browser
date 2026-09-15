# remote-browser

A web browser that runs on somebody else's machine, inside a microVM, and arrives
on yours as a video stream — packaged as two [Celaut](https://github.com/celaut-project/nodo)
services so that starting one is `nodo execute` and nothing else.

## Why this exists

A browser is the largest attack surface most people run, and it is the one program
they point at code they have never read, several hundred times a day. The usual
answers are a second machine, a VM you maintain yourself, or a hosted service that
watches everything you do. Celaut already has the parts for the first two: a node
runs a service in a microVM, on its own hardware or on a peer's, and the service's
specification says up front what it may reach.

So the useful thing to build is not a sandbox. It is a browser whose isolation is
a property of a specification anyone can read, whose engine and flags and fonts
are fixed by a content hash, and which can be handed to a machine with cores to
spare without either end being configured for the other.

The stream is GameStream — [Sunshine](https://github.com/LizardByte/Sunshine) on
the host side, [Moonlight](https://moonlight-stream.org) on yours — because it was
built for interactive latency rather than for playback.

## The two services

```
  your node                                    wherever the balancer put it
┌───────────────────────────┐                ┌──────────────────────────────┐
│  remote-browser (viewer)  │   GameStream   │  remote-browser-engine       │
│  256 MB, 1 core           │ ─────────────▶ │  2–6 GB, 2–4 cores           │
│                           │ ◀───────────── │                              │
│  launches the child       │   H.264 + PCM  │  Xvfb ← Chromium             │
│  holds its credentials    │                │  Sunshine (x264, software)   │
│  brokers the pairing PIN  │                │  pulseaudio null sink        │
│  answers on :8080         │                │  network: *                  │
│  network: [] (nothing)    │                └──────────────────────────────┘
└───────────────────────────┘
```

The split is not decoration. The viewer declares `"network": []` — it speaks to
its node and to its child and to nothing else — while the child declares `["*"]`,
because a browser's destinations are chosen a link at a time and cannot be
enumerated in a file written beforehand. Keeping them in one service would mean
one specification with open egress covering both, and no way to say in it that the
half holding your credentials never leaves the node.

It is also what makes the child's ports usable at all; see *The port problem*.

### What the viewer does

1. Reads its dependency's content hash out of `.dependencies`, so the child is
   asked for by digest and never by name.
2. Generates an administrator password for the child's Sunshine, per session,
   and passes it in `Configuration.environment_variables`. It is not in the
   child's image, so it is not in the child's content hash, and two instances of
   the same digest do not share it.
3. Launches the child and waits for its port to accept a connection — not for the
   node's readiness signal, which fires when the guest's *IP* answers, seconds
   before anything inside has bound anything. Nodo's own log names the gap:
   `instance registered before the guest could call in`.
4. Serves `GET /session` (where the child is, what it was launched with, what is
   wrong with this particular node's answer) and `POST /pair` (one PIN, no
   password).
5. Stops the child when it stops. A leaked instance keeps drawing MU from this
   instance's balance, which is the balance paying for the session.

What it does **not** do yet is show you the stream. That needs a display, and a
nodo guest has no path to one — not a narrow path, none. `NODE-REQUIREMENTS.md`
walks through the four mechanisms that look like they would work, why each fails,
and the two ways to fix it. Until then the stream is collected by a Moonlight
running where there is a screen, and the viewer is what turns that into one
command rather than six.

### What runs inside the child

| | | why this one |
|---|---|---|
| **Chromium** `150.0.7871.181` | the browser | Google publishes no Chrome for `linux/arm64`. On this architecture Chromium is not a substitution, it is the only build that exists. |
| **Xvfb** `21.1.16` | the display | The guest kernel has `# CONFIG_DRM is not set` and `# CONFIG_FB is not set`, so the framebuffer has to be one an X server allocates in ordinary memory. Xvfb also needs no VT, which is switched off too. |
| **Sunshine** `2026.914.233613` | capture + encode + protocol | `capture = x11`, and that is forced: Sunshine's Wayland capture is built on `wlr-export-dmabuf`, a dmabuf needs a DRM device, and KMS capture needs the same one. XShm is shared memory and no device, which makes it the only one of the three paths that runs on this kernel. |
| **x264** via Sunshine | the encoder | `celaut.Sysresources` has no accelerator field. A service cannot ask a node for a GPU, so an encoder that needs one cannot be scheduled anywhere on this network. |
| **PulseAudio** `17.0` | a sound card that does not exist | `# CONFIG_SOUND is not set`, but `module-null-sink` opens no device — it is arithmetic on a buffer — and its monitor is a capture source as far as the encoder cares. The only part of this service that needed nothing from the node. |

Chromium runs as an unprivileged user with its own sandbox on, rather than as root
with `--no-sandbox`. The guest kernel has `CONFIG_USER_NS=y` and
`CONFIG_SECCOMP_FILTER=y`, so every layer it wants is there, and this is the one
service on the network whose job is to open pages nobody vetted. The microVM is
the boundary that matters; it is not a reason to drop the one inside it.

## What it costs to encode on a CPU

This is the number that decides whether the service is pleasant or not, so it
should be near the top rather than in a footnote.

Two software costs stack. Chromium rasterises every frame without a GPU, and x264
encodes every frame after it. On the four cores the child's `at_most` asks for, at
`ultrafast` with `zerolatency`, the honest target is **1080p30** or **720p60** —
not 1080p60, and not 4K at any frame rate. Pages of text, mail, documents, code
review are fine. Video, WebGL, anything expecting a compositor to do its work is
where the absence of a GPU stops being an abstraction.

`SW_PRESET` is the knob. `ultrafast` is the default because latency is the thing
being bought; `veryfast` gives visibly better quality per bit and wants roughly
double the cores.

## The port problem

GameStream does not discover a host's ports. It **derives** them: one base, and a
fixed set of offsets — `47989` for HTTP, base−5 for HTTPS, base+21 for RTSP,
base+9 and up for the four datagram flows. Nodo publishes each declared slot on a
port taken independently from `network.FREE_PORTS_RANGE`, so the offsets between
them are whatever its allocator had free. A Moonlight pointed at the published
HTTP port then computes four wrong ports for everything else and fails in a way
that looks like a network fault.

The offsets survive in exactly one case: when the node advertises the guest's own
bridge address with the internal ports unchanged. That is the case the viewer is
in — it is a sibling on the same bridge, and it dials the child directly — which
is the second reason the viewer is a service rather than a program on your laptop.

`GET /session` reports whether they survived on *this* node, and when they did
not, what to do: one `nodo tunnel <token> <slot> --listen <same slot>` per port
rebuilds the family on the caller's side. Note that tunnelling the four UDP flows
has a cost of its own — `TUNNELING.md` is explicit that datagrams through the
tunnel become reliable and can head-of-line block, which for a video stream is
precisely the property you were avoiding by using UDP. Direct exposure is the
right answer for the media ports; the tunnel is the fallback.

## The interface

HTTP on **8080**, three routes, `http.server` from the standard library. There is
no framework in this image: one endpoint set does not need one, and a dependency
here would be a dependency in the content hash.

```
GET  /session   where the child is, what it was launched with, and what is wrong
                with this node's answer (see "caveats" — it is not decoration)
GET  /health    503 until the child is answering, 200 after
POST /pair      {"pin": "1234"}  →  applies it to the child's Sunshine
```

`POST /pair` is the one that earns the viewer its place. Sunshine's pairing needs
an administrator password; Moonlight's side of it needs a four-digit PIN. Without
the broker you would publish port 47990 to whoever is driving the session and hand
them a password that can rewrite the encoder, the capture method and the
application list on a machine they do not own. With it they send four digits.

The order is the unintuitive one and it is worth stating: **Moonlight generates
the PIN and shows it to you; the host is what enters it.** So `POST /pair` only
does anything while a client is already mid-handshake.

## The environment it reads

| variable | | what it is |
|---|---|---|
| `START_URL` | `about:blank` | The page the session opens on. |
| `WIDTH` / `HEIGHT` | `1920` / `1080` | Stream resolution. Both must be even — H.264 chroma subsampling, and the service refuses rather than producing a stream that decodes wrong. |
| `FPS` | `30` | See *What it costs to encode on a CPU* before raising it. |
| `SW_PRESET` | `ultrafast` | An x264 preset. The latency/quality/cores knob. |
| `LOCALE` | `en-US` | Chromium's `--lang`. |
| `TIMEZONE` | `UTC` | The child's `TZ`. A browser reports it, so leaving it at the default is the private choice and setting it is the convenient one. |
| `CHILD_READY_TIMEOUT_S` | `180` | How long to wait for the child's port. A microVM booting Chromium is not fast, and the default is generous on purpose. |
| `CHILD_INITIAL_MU` | unset | MU to fund the child with. Unset is the right default: the node then funds it for `deposits.INITIAL_RUNTIME_HOURS` of the resources it actually asked for, which any constant here would replace with a flat guess. |

## Resources

| | `at_init` | `at_most` |
|---|---|---|
| **viewer** memory | 256 MB | 768 MB |
| **viewer** disk | 2 GB | 3 GB |
| **viewer** CPU | 1 core | 2 cores |
| **child** memory | 2 GB | 6 GB |
| **child** disk | 6 GB | 12 GB |
| **child** CPU | 2 cores | 4 cores |

The child is declared again in the viewer's `possible_environment_workload`, as a
single scenario with one workload at the child's own `at_most` — the worst case
the node checks it could place *before* admitting the launch. One instance, not
`MAX_SESSIONS` of them: a second browser is a second `nodo execute`, which keeps
the worst case one browser and keeps the accounting per session.

The viewer's disk is larger than a service holding four Python files needs, and
the reason is stated rather than trimmed: the image also carries the client
library, and it is sized for the Moonlight that goes in when there is somewhere to
draw.

## Network

```json
"network": []                  // the viewer
"network": [{ "tags": ["*"] }] // the child
```

`[]` on the viewer is a real claim, checked by the node's firewall: the only host
address a guest is granted is the node's own gateway, and the only other thing it
reaches is a child it launched. Your credentials, the session's addresses and the
administrator password for the child are all on that side of the line.

`["*"]` on the child is the honest form of "this is a browser". The narrower
alternative is not narrower in the way it looks: nodo resolves a domain tag to
that domain's A records **on ports 80 and 443 only**, at launch, once. A list of
domains would be a list of the sites you had thought of, pinned to the addresses
they had that afternoon — a worse description of what a browser does than the
wildcard, and one that would fail in a way nobody could read.

A node operator can refuse it. `service_networks.blacklist: ["*"]` refuses every
service declaring any tagged network, and that is the control that matters here:
the declaration exists so the refusal can be made before the launch, rather than
discovered from a packet capture after it.

## Where "another PC" comes from

Both services declare `linux/arm64`, and it is worth being exact about what that
does and does not guarantee: **it does not force the browser onto another
machine.** Placement is the balancer's call — `network.DELEGATE_EXECUTION` and the
peers your node knows — and a node with the cores free will run the child itself.
For a machine that is already your desktop, that is often what you want; the
isolation is the microVM, and it holds either way.

If the child genuinely has to be elsewhere, the lever is the same one
[`conversation-profiler`](https://github.com/copa-ai/conversation-profiler) uses:
declare it `linux/amd64` and an arm64 fleet cannot run it natively, so it goes to
an x86 peer or nowhere. One warning goes with that, and it is not a small one.
`virtualizers.qemu.ENABLE` defaults to **true**, so a node with no x86 will accept
the job anyway and run it under TCG emulation — nodo's own configuration calls
that "an order of magnitude slower than KVM". For a proxy that is a reasonable
default; for Chromium and an x264 encoder it is the difference between a session
and a slideshow. Turn it off, or expect the node to crawl rather than refuse.

## Reproducibility, and what it can mean here

Celaut asks that the same input give the same output, and an interactive browser
is the clearest case on the network where that cannot mean what it usually means.
The output is a session. It depends on what you click, on what the sites answered,
on the minute it ran. No amount of pinning changes that, and pretending otherwise
would be the dishonest version of this section.

What content-addressing buys here is the *environment*, and that is not a
consolation prize:

- the base image by digest and every Debian package by its exact version, so a
  security update cannot silently change which browser you ran;
- Sunshine by version **and by the sha256 GitHub publishes for that asset** — it
  is not in Debian, so it arrives over the network at build time, which makes it
  exactly the input that has to be nailed down;
- `celaut-service-libraries` by commit, not by branch. An unpinned `git+…`
  resolves to whatever the default branch happened to be that afternoon, so two
  packs of an unchanged tree produce two different images and a bug seen in a
  running instance cannot be traced to a revision;
- the child by content hash, from `.dependencies`. Swapping the browser is a
  digest in a diff, which is the point of asking for it that way.

So two people running the same digest ran the same Chromium, with the same flags,
the same fonts, the same encoder and the same preset. They did not see the same
pixels, and were never going to.

## Pack

```bash
nodo pack browser        # the child first: the parent needs its digest
nodo pack .              # dependencies_env writes it into .dependencies
```

`architecture` is `linux/arm64` in both. The packer builds for the host it runs
on, so change both to match yours.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Ten, and they need neither a node nor `node_controller`: the library's imports are
guarded so that the two pieces of this service that contain real reasoning can be
run on their own. Those two are `config.resolve`, where a string somebody typed
becomes a number the child is launched with, and `Child.offsets_survived`, which
decides whether this node's port allocator left a session a client can open. Both
fail three layers away from where the mistake was made, which is the argument for
asserting them here.

## What this is not

- **Not anonymity.** Your traffic leaves the node running the child, with that
  node's address. If the balancer sent the child to a peer, it leaves from the
  peer — and browsing on someone else's connection is a thing to decide
  deliberately, not to discover from `/session`.
- **Not confidential from the node.** The operator of the machine running the
  child can read the page: it is rendered in their RAM. Celaut's isolation is
  between *services*, and what is between you and an operator is their reputation.
  `TUNNELING.md` makes the same point about relayed traffic and is worth reading
  in the same spirit.
- **Not a persistent profile by default.** The profile lives in the child's own
  disk, which is the child's, which ends when the instance does. That is the right
  default for this service and it means your logins do not survive a session.
- **Not view-only by choice.** It is view-only on an unmodified node, because
  Sunshine injects input through `/dev/uinput` and nodo's guest kernel is built
  with `# CONFIG_INPUT is not set`. Requirement 1 of `NODE-REQUIREMENTS.md`.

## Status

Specification and implementation, neither packed nor run.

Written: both `.service/` trees, the child's entrypoint, and the viewer — config,
child lifecycle, the Sunshine client and the HTTP API. Every version, digest and
checksum in the two Dockerfiles was checked against the Debian archive and the
GitHub release it names, on 2026-09-15. The settings and slot logic have tests and
they pass.

Not yet true of any of it: `nodo pack` has not been run, no instance has started,
and no Moonlight has connected. Three things in particular are written from
documentation rather than from a running system, and are where to look first when
it does not work — Sunshine's configuration keys, the `POST /api/pin` request
shape, and whether Sunshine's X11 capture is happy with a display no compositor
ever touched.

And the honest summary of the rest: on an unmodified node this shows you a browser
and does not let you touch it. That is not a bug to be found in this repository,
it is Requirement 1, and it is two symbols in a kernel configuration file.
