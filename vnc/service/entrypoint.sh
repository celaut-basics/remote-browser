#!/bin/bash
# PID 1 of remote-browser-vnc.
#
# Two processes. Xvnc is the X server and the RFB server at once, so there is no
# capture step: the framebuffer it hands to a viewer is the one Chromium drew in.
# And input arrives through XTEST, an extension of the X server itself, so nothing
# here needs /dev/uinput -- which is the whole reason this architecture runs on an
# unmodified node with no kernel input subsystem at all.
set -euo pipefail

log() { printf '%s [vnc] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
fail() { log "FATAL: $*"; exit 1; }

VNC_PASSWORD="${VNC_PASSWORD:-}"
START_URL="${START_URL:-about:blank}"
WIDTH="${WIDTH:-1920}"
HEIGHT="${HEIGHT:-1080}"
LOCALE="${LOCALE:-en-US}"
TIMEZONE="${TIMEZONE:-UTC}"
DNS_SERVERS="${DNS_SERVERS:-}"

STATE=/var/lib/browser
LOGS=/var/log/browser
PASSWD=/run/vnc/passwd

# --- Values from the launcher ---------------------------------------------------
#
# Refused at start rather than passed on. Each one reaches a command line or a
# configuration file below, and a bad value there fails later, in a log nobody
# reads, or not at all. START_URL is the sharp one: it is the last argument to
# Chromium, so a value that begins with `-` would be read as a Chromium switch.
need_int() {
  [[ "$2" =~ ^[0-9]{1,5}$ ]] && [ "$2" -ge "$3" ] && [ "$2" -le "$4" ] \
    || fail "$1 must be an integer from $3 to $4, got '$2'"
}
need_int WIDTH "$WIDTH" 320 7680
need_int HEIGHT "$HEIGHT" 240 4320
[[ "$START_URL" != -* ]] || fail "START_URL must not begin with '-', got '$START_URL'"
[[ "$LOCALE" =~ ^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$ ]] \
  || fail "LOCALE must be a language tag such as en-US, got '$LOCALE'"
[[ "$TIMEZONE" =~ ^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$ ]] \
  || fail "TIMEZONE must be a zone name such as Europe/Madrid, got '$TIMEZONE'"

export DISPLAY=:0
export TZ="$TIMEZONE"
mkdir -p "$STATE" "$LOGS"
chown -R browser:browser "$STATE" "$LOGS"

# --- Name resolution ------------------------------------------------------------
#
# nodo serves no DNS to a guest and writes no resolv.conf into it: name resolution
# is the service's job (src/virtualizers/microvm/network.py). This service declares
# `*`, so it can reach a public resolver on port 53, but only if resolv.conf names
# one. The Debian base image names Cloudflare (1.1.1.1, 1.0.0.1), and that is kept
# when DNS_SERVERS is unset. DNS_SERVERS replaces it with up to three IPv4
# addresses, because the resolver sees every name this browser looks up.
if [ -n "$DNS_SERVERS" ]; then
  read -r -a servers <<<"${DNS_SERVERS//,/ }"
  [ "${#servers[@]}" -le 3 ] || fail "DNS_SERVERS names ${#servers[@]} servers; glibc reads 3"
  : >/etc/resolv.conf.new
  for server in "${servers[@]}"; do
    [[ "$server" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] \
      || fail "DNS_SERVERS: '$server' is not an IPv4 address"
    printf 'nameserver %s\n' "$server" >>/etc/resolv.conf.new
  done
  mv /etc/resolv.conf.new /etc/resolv.conf
elif ! grep -q '^nameserver ' /etc/resolv.conf 2>/dev/null; then
  printf 'nameserver %s\n' 1.1.1.1 1.0.0.1 >/etc/resolv.conf
fi
log "dns: $(awk '/^nameserver /{printf "%s ", $2}' /etc/resolv.conf)"

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
     nodo execute -e VNC_PASSWORD <something> remote-browser-vnc
   Note that RFB truncates it to 8 bytes whatever you choose."

if [ "${#VNC_PASSWORD}" -gt 8 ]; then
  log "note: VNC_PASSWORD is ${#VNC_PASSWORD} characters and RFB will use the first 8"
fi

# /run is a tmpfs, mounted fresh and empty on every boot -- by nodo's initramfs
# and by any systemd host alike. A directory made there at build time is gone
# before this line runs, so it is made here and not in the Dockerfile (issue #2).
# (/var/lib/browser and /var/log/browser are fine: only /run and /tmp are wiped.)
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
# /dev/shm: the nodo guest init mounts a tmpfs there, sized at half the guest's
# memory, and Chromium moves every frame between its processes through it. So
# --disable-dev-shm-usage, which moves that traffic to /tmp on the disk, is set
# only when /dev/shm is small, as it is in a default container (64 MiB).
#
# There is no audio in this architecture. RFB carries none.
shm_flags=()
shm_kib="$(df -Pk /dev/shm 2>/dev/null | awk 'NR == 2 { print $4 }')"
if [ "${shm_kib:-0}" -lt 524288 ]; then
  shm_flags=(--disable-dev-shm-usage)
  log "note: /dev/shm has ${shm_kib:-0} KiB free; chromium will use /tmp instead"
fi

log "starting chromium at ${START_URL}"
runuser -u browser -- \
  env DISPLAY=:0 TZ="$TZ" \
  chromium \
    --kiosk \
    --no-first-run \
    --no-default-browser-check \
    --disable-gpu \
    "${shm_flags[@]}" \
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
