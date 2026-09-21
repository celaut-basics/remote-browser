# What `remote-browser-waypipe` needs

## From the node

**One thing, and it does not exist yet: a way to run the host end of the channel.**
Everything else this architecture needs, it already has.

| | status |
|---|---|
| `/dev/uinput` | **not needed.** Input arrives as ordinary Wayland — `wl_pointer.motion`, `wl_keyboard.key` — from the user's own compositor, through the same channel the pixels come back on. `# CONFIG_INPUT is not set` costs this architecture nothing. |
| `/dev/dri` | **not needed**, and its absence is not neutral — see *What it costs* below. |
| a sound device | **not needed**, because there is no audio at all. Wayland carries none. |
| a TCP slot | **have it.** The channel is a declared slot like any other. |
| something to drive the host end | **missing.** Three commands by hand today; [`nodo display`](https://github.com/celaut-project/nodo/issues/367) is the proposal. |

That last row is the only real requirement, and it is a convenience rather than a
capability: the three commands work, and the command would collapse them.

## From the host

- **A Wayland session.** Any compositor — GNOME, KDE, Hyprland, sway. There is no
  X11 fallback: the whole mechanism is that `waypipe client` becomes an ordinary
  Wayland client of your compositor.
- **`waypipe` and `socat`.** Both are packaged everywhere.

```bash
nodo tunnel <instance> 8081 --listen 8081 &
waypipe --socket /tmp/wp-client.sock client &
socat UNIX-CONNECT:/tmp/wp-client.sock TCP:127.0.0.1:8081
```

The third command is the direction reversal. `waypipe client` listens where the
compositor is and `waypipe server` dials from where the application is — but the
guest cannot dial the host, so the host dials in and `socat` bridges the two. The
service side does the mirror image of this; `service/entrypoint.sh` explains why
its `socat` invocation orders its addresses the way it does.

## How a window appears, since it is not obvious

Nothing about a window is transported. A window **is** a sequence of messages on a
socket: bind `wl_compositor` and `xdg_wm_base`, create a `wl_surface`, wrap it in
an `xdg_surface` and an `xdg_toplevel`, attach a `wl_buffer`, commit. Anything
that replays that sequence against a compositor has made a window.

What stops the socket simply being piped is that the protocol passes **file
descriptors** as `SCM_RIGHTS` — `wl_shm.create_pool(fd, size)` for the pixels,
`wl_keyboard.keymap(fd, size)` for the xkb keymap. An fd indexes one process's
table in **one kernel**, so copying the socket's bytes across leaves the far side
holding a number that means nothing.

So waypipe is a translator, not a tunnel. Here, it offers Chromium a fake
compositor socket, parses only the fd-carrying messages, mmaps each shm region,
keeps a private copy and sends the runs that changed. On the host, `waypipe
client` creates a **local** memfd, fills it from the channel, and replays the
attach, the damage and the commit against the real compositor — which sees a
normal local client and never learns a VM exists. Input returns the same way.

## What it costs, which is the reason this is not the only architecture

`# CONFIG_DRM is not set` means no `/dev/dri`, no dmabuf, and therefore every
buffer is `wl_shm`. waypipe's own `--video` is documented as *"Compress specific
DMABUF formats using a lossy video codec"* and does not apply. What is left is
diffing and lz4.

So the cost is **proportional to how much of the screen changes**, not to the
resolution:

| | damage per frame at 1080p | measured |
|---|---|---|
| still page, cursor blinking | hundreds of bytes | **zero** |
| scrolling text | whole screen, but lz4 does well on text (3–5×) → ~2 MB | **~0.65 MB**, lz4 got 12.8× |
| video, GIF, carousel, CSS animation | the worst case, ~8.3 MB | not measured |

That is excellent for most GUI programs and awkward for a browser specifically,
because scrolling is full-screen damage and scrolling is what one does in a
browser. The cost is bursty, and the bursts land on the moments of interaction.

**Measured, 2026-09-15**, against a real channel — Chromium in this image under
`waypipe server`, the `socat` reversal, `waypipe client` and a compositor at the
other end — on a page of monospaced text that scrolls itself at ~30 fps. The screen
was 1280×800; the 1080p column scales by pixel count.

| | 1280×800, measured on the channel |
|---|---|
| idle, page loaded, nothing moving, 15 s | **0 bytes** |
| scrolling, 20 s | 191,742,048 B = **9.59 MB/s** |
| per frame at 30 fps | **0.32 MB** against a 4.10 MB raw frame — **12.8×** |

Two corrections, in opposite directions, and both worth having:

- **lz4 does better on text than 3–5×.** 12.8× here. Monospaced text is the
  compressible extreme, but text is the case this table is about. Scaled to 1080p
  that is ~0.65 MB a frame rather than ~2 MB, and ~70 GB/hour of continuous
  scrolling rather than the order of 360 GB/hour below. Still twenty times H.264's
  3.6 GB/hour, so the verdict does not move: the estimate was pessimistic, not
  wrong.
- **Idle is not "hundreds of bytes", it is nothing.** Zero bytes in 15 seconds on
  a loaded, still page. Nothing commits, so nothing is sent — and the architecture's
  best case is better than it claimed.

**And a cost that only shows up in the bill.** Tunnelled,
`pricing.NET_MU_PER_GIB` meters this: damage rates run on the order of 360 GB/hour
against 3.6 GB/hour for H.264 at 8 Mbps. Directly exposed rather than tunnelled it
is not metered — *"Only what crosses this relay is counted"* — so it depends on
the deployment.

**Verdict:** the right architecture when the browser is on your own machine or a
LAN. The wrong one across a real network, which is the case that motivated this
repository in the first place.
