#!/bin/bash
# PID 1 of remote-browser-vnc.
#
# Two processes. Xvnc is the X server and the RFB server at once, so there is no
# capture step: the framebuffer it hands to a viewer is the one Chromium drew in.
# And input arrives through XTEST, an extension of the X server itself, so nothing
# here needs /dev/uinput -- which is the whole reason this architecture runs on an
# unmodified node and the GameStream one does not.
set -euo pipefail

log() { printf '%s [vnc] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
fail() { log "FATAL: $*"; exit 1; }

VNC_PASSWORD="${VNC_PASSWORD:-}"
START_URL="${START_URL:-about:blank}"
WIDTH="${WIDTH:-1920}"
HEIGHT="${HEIGHT:-1080}"
LOCALE="${LOCALE:-en-US}"
TIMEZONE="${TIMEZONE:-UTC}"

STATE=/var/lib/browser
LOGS=/var/log/browser
PASSWD=/run/vnc/passwd

export DISPLAY=:0
export TZ="$TIMEZONE"
mkdir -p "$STATE" "$LOGS"
chown -R browser:browser "$STATE" "$LOGS"

# --- The password, and its ceiling --------------------------------------------
#
# Refusing rather than defaulting: without a password Xvnc would hand a browser
# session to anything that can open port 5900, which on this node is every other
# guest on the bridge.
#
# But know what this buys, because it is less than it looks. RFB's VncAuth is a
# DES challenge-response over a key of at most EIGHT BYTES -- the protocol
# truncates anything longer, silently. That is a property of RFB, not of TigerVNC
# and not of this service, and no length of VNC_PASSWORD escapes it.
#
# So the password is a guard against a stray connection, not a credential. Reach
# this service through `nodo tunnel`, which is TLS to the node and authorised by
# the instance token, rather than by publishing 5900. See NODE-REQUIREMENTS.md.
[ -n "$VNC_PASSWORD" ] || fail \
  "VNC_PASSWORD is unset. Pass it at launch:
     nodo execute remote-browser-vnc -e VNC_PASSWORD <something>
   Note that RFB truncates it to 8 bytes whatever you choose."

if [ "${#VNC_PASSWORD}" -gt 8 ]; then
  log "note: VNC_PASSWORD is ${#VNC_PASSWORD} characters and RFB will use the first 8"
fi

# /run is a tmpfs, mounted fresh and empty on every boot -- by nodo's initramfs
# and by any systemd host alike. The `mkdir -p /run/vnc` in the Dockerfile ran at
# build time and is gone before this line ever runs, so the directory has to be
# made here. (/var/lib/browser and /var/log/browser are fine: only /run and /tmp
# are wiped.)
mkdir -p "$(dirname "$PASSWD")"
chmod 700 "$(dirname "$PASSWD")"
chown browser:browser "$(dirname "$PASSWD")"

command -v vncpasswd >/dev/null 2>&1 \
  || fail "vncpasswd not found; it ships in tigervnc-tools, not tigervnc-common"
printf '%s\n' "$VNC_PASSWORD" | vncpasswd -f > "$PASSWD" \
  || fail "vncpasswd failed writing $PASSWD"
chmod 600 "$PASSWD"
chown browser:browser "$PASSWD"

# --- Xvnc ---------------------------------------------------------------------
#
# -localhost no because the client is not on this machine: it reaches the slot
# from the bridge or through a tunnel. -AlwaysShared so a reconnect does not
# displace a session that is still open.
log "starting Xvnc at ${WIDTH}x${HEIGHT}x24 on :0, RFB on 5900"
runuser -u browser -- \
  Xvnc :0 \
    -geometry "${WIDTH}x${HEIGHT}" \
    -depth 24 \
    -rfbport 5900 \
    -rfbauth "$PASSWD" \
    -SecurityTypes VncAuth \
    -localhost no \
    -AlwaysShared \
    -desktop remote-browser \
  >"$LOGS/xvnc.log" 2>&1 &
XVNC_PID=$!

for _ in $(seq 1 100); do
  runuser -u browser -- xdpyinfo -display :0 >/dev/null 2>&1 && break
  sleep 0.1
done
runuser -u browser -- xdpyinfo -display :0 >/dev/null 2>&1 \
  || fail "Xvnc never answered on :0 (see $LOGS/xvnc.log)"
log "display :0 is up"

# --- Chromium -----------------------------------------------------------------
#
# --disable-gpu: the guest kernel has `# CONFIG_DRM is not set`, so there is no
# /dev/dri and software rasterisation is what is left.
#
# There is no audio in this architecture. RFB carries none.
log "starting chromium at ${START_URL}"
runuser -u browser -- \
  env DISPLAY=:0 TZ="$TZ" \
  chromium \
    --kiosk \
    --no-first-run \
    --no-default-browser-check \
    --disable-gpu \
    --disable-dev-shm-usage \
    --window-size="${WIDTH},${HEIGHT}" \
    --window-position=0,0 \
    --lang="${LOCALE}" \
    --user-data-dir="${STATE}/profile" \
    --disk-cache-dir="${STATE}/cache" \
    "${START_URL}" \
  >"$LOGS/chromium.log" 2>&1 &
CHROMIUM_PID=$!

log "up: xvnc=${XVNC_PID} chromium=${CHROMIUM_PID}"

# Neither is optional: without Xvnc there is nothing to connect to, and a browser
# that died leaves a viewer looking at a grey rectangle that is indistinguishable
# from a working service.
wait -n
log "a child process exited; shutting the instance down"
kill "$XVNC_PID" "$CHROMIUM_PID" 2>/dev/null || true
exit 1
