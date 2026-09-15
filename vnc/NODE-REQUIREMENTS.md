# What `remote-browser-vnc` needs

## From the node

**Nothing.** This is the whole point of the architecture, and it is worth being
specific about what "nothing" means, because the other two both need something:

| | why it is not needed here |
|---|---|
| `/dev/uinput` | Input arrives through **XTEST**, an extension of the X server itself. `Xvnc` receives an RFB `PointerEvent` and calls into its own input pipeline; nothing goes near the kernel's input subsystem, so `# CONFIG_INPUT is not set` costs nothing. |
| a display channel | An RFB server **listens**. That is the natural shape of a celaut slot, so the slot is the whole of the plumbing — no direction to reverse, no `socat`, no command that does not exist yet. |
| `/dev/dri` | `Xvnc` allocates its framebuffer in ordinary memory and Chromium rasterises into it in software. `# CONFIG_DRM is not set` is not a constraint here, it is simply irrelevant. |
| a GPU | The encodings RFB uses (Tight, ZRLE) are CPU work by design and were built for exactly this. `celaut.Sysresources` has no accelerator field, which costs this architecture nothing. |
| a sound device | See below — there is no audio at all, so `# CONFIG_SOUND is not set` costs nothing either. |

## From the host

- **A VNC viewer.** Any of them. TigerVNC, Remmina, KRDC, RealVNC, macOS Screen
  Sharing, the one built into your file manager. This is the only architecture of
  the three whose client is something people already have.
- **`nodo tunnel`, and preferably not a published port.** See below.

```bash
nodo tunnel <instance> 5900 --listen 5900
vncviewer 127.0.0.1:5900
```

## What the host should be careful about

**RFB's `VncAuth` is a DES challenge-response over a key of at most eight bytes.**
The protocol truncates anything longer, silently. That is RFB, not TigerVNC and
not this service, and no choice of `VNC_PASSWORD` escapes it.

So treat the password as a guard against a stray connection on the bridge, and not
as the thing protecting the session. What should protect it is the tunnel: `nodo
tunnel` is TLS to the node, pinned to the node's identity key, and authorised by
possession of the instance token. Publishing 5900 and relying on eight characters
is the configuration to avoid.

TigerVNC does support TLS security types (`TLSVnc`, `X509Vnc`), which would be the
in-band answer. They need a certificate, and a certificate needs a name the two
ends agree on — which an instance reached through a port allocator does not have.
That is why this service does not try, and why the tunnel is the answer instead.

## What this architecture does not have

**Audio.** RFB carries none. Neither does the waypipe architecture; only the
GameStream one does. If sound matters, this is not the one.

**Latency comparable to GameStream.** RFB was designed for desktops rather than
for motion, and it shows in the same place its encodings shine: excellent on a
still page, clearly worse than H.264 once things move. It is the middle of the
three on purpose.
