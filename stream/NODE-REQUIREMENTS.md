# What `remote-browser` (GameStream) needs

## From the node

**Two symbols in the guest kernel, and without them this service is view-only.**

```
CONFIG_INPUT=y
CONFIG_INPUT_UINPUT=y
```

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

The reasoning in that comment is correct **about hardware**. A microVM has no USB
and no PS/2, so the HID drivers are dead weight. But `CONFIG_INPUT` is the
subsystem those drivers hang off, and switching it off also removes `uinput`,
which needs no hardware at all: it is a character device that lets a userspace
process *create* a virtual input device and write events into it. The kernel then
exposes an ordinary `/dev/input/eventN` that nothing downstream can tell from a
real keyboard. It is collateral damage — the switch was thrown for the drivers and
it took out the door as well.

And there is no second path. `XTestFakeKeyEvent` appears nowhere in Sunshine's
source, and its packaging ships a udev rule for `/dev/uinput`, which is what a
hard dependency looks like.

### The case, on the terms the config file sets

That file says of itself: *"Keep this file as the single source of truth for what
a Nodo microVM guest can do. Adding a feature here is a decision about every
service on the network."* Which is the right standard, so:

- **What it lets a guest do that it could not before:** create a virtual input
  device inside its own guest and write events to it. There is no host side. A
  uinput device is private to the kernel that created it, and a nodo guest kernel
  is one per instance, so a guest that invents a keyboard can only inject events
  into **itself**. Nothing crosses a boundary that was not already crossed.
- **What it costs every other service:** the input core plus `uinput`, tens of
  kilobytes on an `Image` measured in megabytes, and nothing registered at boot
  because no bus enumerates anything.
- **Who else wants it:** every service that drives a graphical program it did not
  write. And the strongest claims come from services that display *nothing at
  all* — a GUI test runner driving an application nobody watches, a scraper that
  has to click, any automation wrapping a program with no API. That is the
  clearest evidence this is not a display feature.

`CONFIG_HID` and `CONFIG_VT` should stay off. The ask is those two symbols.

### Two ways to avoid asking, and what each costs

- **Inject through X instead.** `XTEST` puts events into an X server from
  userspace with no kernel involvement — it is how `xdotool` works, and it is why
  the sibling `vnc/` architecture needs none of this. Sunshine has no XTEST path,
  so this means carrying a patch against an actively developed GPL-3.0 project,
  forever, for one symbol the kernel could provide.
- **Drive the browser instead of the desktop.** Chromium's DevTools protocol has
  `Input.dispatchMouseEvent`, entirely in userspace. But the events arrive inside
  Sunshine over the GameStream control stream, so getting at them means patching
  Sunshine again, or running input on a side channel no stock client speaks.

## Pairing, which is a request shape and not a page

Moonlight asks to pair, Sunshine holds the request, and something has to answer it
with the PIN. Normally that something is a person on the web UI at 47990; here it
is a `curl`, and the shape below was read off this build rather than off the
documentation — `2026.914.233613`, `src/confighttp.cpp`, confirmed against a
running instance.

```bash
# What is waiting. `pairings` is empty until Moonlight has asked.
curl -sk -u "$ADMIN_USER:$ADMIN_PASS" https://127.0.0.1:47990/api/pin
# {"pairings":[]}

# Answer one.
curl -sk -u "$ADMIN_USER:$ADMIN_PASS" -X POST https://127.0.0.1:47990/api/pin \
     -H 'Content-Type: application/json' \
     -d '{"pairing_id":"<32 hex from the GET>","pin":"<4 digits Moonlight showed>","name":"<anything>"}'
# {"status":true}
```

Four things this build enforces, each of which returns 400 or 401 rather than
failing quietly:

- **`pairing_id` is required**, and it is `exactly 32 hexadecimal characters`.
  TODO.md asked whether this build wants it: it does, and there is no shape
  without it. It is not invented locally — it comes from the `GET`, which is
  Moonlight's own pairing request, so the `POST` is an answer and never an
  opener. A well-formed but unknown id returns `{"status":false}` with HTTP 200,
  which is the one failure here that is not an error code.
- **`pin` is exactly 4 digits**, and **`name` is 1–128 bytes**; both are checked.
- **`Content-Type: application/json` is mandatory** — without it the body is not
  even parsed: `{"error":"Content type mismatch"}`, 400.
- **HTTP basic auth**, which is what `ADMIN_USER`/`ADMIN_PASS` seed. No header,
  401.

There is a CSRF check as well, and it does not apply to this: it requires a token
only when a request carries an `Origin` or `Referer` that is not allowed. `curl`
sends neither, and the code says in as many words that a request with neither
cannot be browser-initiated. A browser pointed at the same endpoint needs the
token.

## From the host

- **Moonlight, installed natively.** Not as a celaut service: a native client
  decodes once and hands the frame to your own compositor with no copy, which is
  the best possible last hop and costs nothing to arrange. Note that Moonlight is
  packaged for Linux `arm64` **nowhere** — not Debian, and upstream ships only an
  `x86_64` AppImage — which is a reason to install it on the host (where your
  distro or Flathub has it) rather than to try to put it in an image.
- **Eight tunnels, or a node that publishes conveniently.** GameStream does not
  discover ports, it *derives* them from one base by fixed offsets, and nodo
  publishes each slot on an independently chosen free port. Rebuild the family
  locally:

```bash
for p in 47989 47984 47990 48010; do nodo tunnel <instance> $p --listen $p & done
for p in 47998 47999 48000 48002; do nodo tunnel <instance> $p --listen $p --udp & done
```

  With the honest caveat that `TUNNELING.md` states plainly: datagrams through the
  tunnel become reliable and can head-of-line block, which for video is the
  property UDP was chosen to avoid. Against a node on your own machine that is a
  non-issue. Against a remote one it is a real cost, and the alternative — direct
  exposure — gives the offsets problem back. Unresolved.

## What this architecture has that the others do not

**Audio**, via a userspace PulseAudio null sink. Neither `waypipe/` nor `vnc/`
carries sound at all.

**A transport that does not care what is on screen.** ~1–2 MB/s whether the page
is still or playing video, which is what makes this the only one of the three
worth running across a real network.
