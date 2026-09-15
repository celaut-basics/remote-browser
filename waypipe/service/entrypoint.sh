#!/bin/bash
# PID 1 of remote-browser-waypipe.
#
# Two processes and no display server. Chromium is an ordinary Wayland client;
# the compositor it talks to is the one on the user's own machine, on the other
# side of a waypipe channel. Nothing here draws, captures or encodes anything.
set -euo pipefail

log() { printf '%s [waypipe] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
fail() { log "FATAL: $*"; exit 1; }

START_URL="${START_URL:-about:blank}"
WIDTH="${WIDTH:-1920}"
HEIGHT="${HEIGHT:-1080}"
LOCALE="${LOCALE:-en-US}"
TIMEZONE="${TIMEZONE:-UTC}"

SLOT=8081
CHANNEL=/run/waypipe/chan.sock
STATE=/var/lib/browser
LOGS=/var/log/browser

export TZ="$TIMEZONE"
export XDG_RUNTIME_DIR=/run/user/1000

rm -f "$CHANNEL"
mkdir -p "$STATE" "$LOGS"
chown -R browser:browser "$STATE" "$LOGS" /run/waypipe

# --- The direction reversal ---------------------------------------------------
#
# waypipe's roles are fixed the wrong way round for a celaut slot. `waypipe
# client` runs where the compositor is and LISTENS; `waypipe server` runs here,
# where the application is, and DIALS. But a slot is something a service listens
# on, and a guest cannot dial the host anyway: `*` egress is written on the
# FORWARD hook, while the host's own addresses are matched on INPUT, where nodo
# grants a guest exactly one thing -- the node's gateway.
#
# So the host dials in and socat stands between the two. Its accept order is what
# makes this work, and it is a property worth relying on deliberately: socat
# accepts on its FIRST address and only then creates and accepts on the second.
# The slot therefore listens from boot, and $CHANNEL appears at exactly the moment
# a session begins -- which is the moment, and the only moment, at which
# `waypipe server` can successfully dial it.
log "listening on slot ${SLOT}; the session begins when something connects"
runuser -u browser -- \
  socat "TCP-LISTEN:${SLOT},reuseaddr" "UNIX-LISTEN:${CHANNEL}" \
  >"$LOGS/socat.log" 2>&1 &
SOCAT_PID=$!

# Poll rather than sleep a fixed amount: the wait is for an event (the host
# connecting), not for a duration, and it has no deadline -- an instance nobody
# has connected to yet is not a failed instance.
log "waiting for a client"
while [ ! -S "$CHANNEL" ]; do
  kill -0 "$SOCAT_PID" 2>/dev/null || fail "socat exited before any client connected (see $LOGS/socat.log)"
  sleep 0.2
done
log "client connected; channel is up at ${CHANNEL}"

# --- Chromium, as a Wayland client -------------------------------------------
#
# --disable-gpu, and software rasterisation is what is left: the guest kernel has
# `# CONFIG_DRM is not set`, so there is no /dev/dri to fall back from. That also
# fixes what waypipe has to carry -- every buffer is wl_shm, so its own --video
# ("Compress specific DMABUF formats using a lossy video codec") cannot apply, and
# the cost of a frame is proportional to how much of it changed. Reading a page is
# nearly free. Scrolling one is a whole framebuffer.
#
# There is no audio in this architecture. Wayland carries none, and waypipe
# carries Wayland; a sound path would be a second channel and it is not here.
log "starting chromium at ${START_URL} (${WIDTH}x${HEIGHT})"
exec runuser -u browser -- \
  env XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" TZ="$TZ" \
  waypipe --socket "$CHANNEL" server \
    chromium \
      --kiosk \
      --no-first-run \
      --no-default-browser-check \
      --ozone-platform=wayland \
      --disable-gpu \
      --disable-dev-shm-usage \
      --window-size="${WIDTH},${HEIGHT}" \
      --lang="${LOCALE}" \
      --user-data-dir="${STATE}/profile" \
      --disk-cache-dir="${STATE}/cache" \
      "${START_URL}"

# `exec`, so waypipe is PID 1 from here: when the session ends, the instance ends.
# One session per instance is deliberate. waypipe has a `recon` subcommand for
# reattaching a server to a new channel, which would let the browser outlive a
# disconnection, and wiring it up is in TODO.md rather than guessed at here.
