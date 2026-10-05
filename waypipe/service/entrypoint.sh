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
DNS_SERVERS="${DNS_SERVERS:-}"

SLOT=8081
CHANNEL=/run/waypipe/chan.sock
STATE=/var/lib/browser
LOGS=/var/log/browser

# --- Values from the launcher ---------------------------------------------------
#
# Refused at start rather than passed on; see the same block in vnc/. START_URL
# is the last argument to Chromium, so a value that begins with `-` would be read
# as a Chromium switch.
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

export TZ="$TIMEZONE"
export XDG_RUNTIME_DIR=/run/user/1000

# /run is a tmpfs mounted empty on every boot, so /run/waypipe and /run/user/1000
# are made here and not in the Dockerfile (issue #2).
mkdir -p "$STATE" "$LOGS" "$(dirname "$CHANNEL")" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
rm -f "$CHANNEL"
chown -R browser:browser "$STATE" "$LOGS" "$(dirname "$CHANNEL")" "$XDG_RUNTIME_DIR"

# --- Name resolution ------------------------------------------------------------
#
# nodo serves no DNS to a guest; see the same block in vnc/. The base image names
# Cloudflare, and DNS_SERVERS replaces it with up to three IPv4 addresses.
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
#
# --- Who may connect ----------------------------------------------------------
#
# waypipe has no authentication, and the first connection gets the session: the
# browser's pixels and its keyboard and mouse. vnc/ has a password and stream/ has
# pairing; this slot has neither. And every other guest on the node's bridge that
# declares `*` can open a connection to it.
#
# So socat accepts only from the node. `nodo tunnel` connects to the slot from the
# node's address on the bridge (src/tunneling/rpc_tunnel.py), and so does a
# client on the node host itself. That address is the guest's default gateway:
# nodo writes it into the kernel's `ip=` parameter. socat closes a connection from
# any other address and keeps listening. A published port reached from another
# machine keeps its own source address through the DNAT, so it is refused too:
# use the tunnel.
node_address() {
  local hex
  hex="$(awk '$2 == "00000000" && $3 != "00000000" { print $3; exit }' /proc/net/route)"
  [[ "$hex" =~ ^[0-9A-Fa-f]{8}$ ]] || return 1
  # /proc/net/route prints the address in host byte order: little-endian here.
  printf '%d.%d.%d.%d\n' "0x${hex:6:2}" "0x${hex:4:2}" "0x${hex:2:2}" "0x${hex:0:2}"
}
LISTEN="TCP-LISTEN:${SLOT},reuseaddr"
if NODE="$(node_address)"; then
  LISTEN="${LISTEN},range=${NODE}/32"
  log "slot ${SLOT} accepts connections from the node (${NODE}) only"
else
  log "WARNING: no default route; slot ${SLOT} accepts a connection from any address"
fi

log "listening on slot ${SLOT}; the session begins when something connects"
runuser -u browser -- \
  socat "$LISTEN" "UNIX-LISTEN:${CHANNEL}" \
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
# --disable-dev-shm-usage only when /dev/shm is small; see the same block in vnc/.
# The nodo guest init mounts a tmpfs there at half the guest's memory.
#
# There is no audio in this architecture. Wayland carries none, and waypipe
# carries Wayland; a sound path would be a second channel and it is not here.
shm_flags=()
shm_kib="$(df -Pk /dev/shm 2>/dev/null | awk 'NR == 2 { print $4 }')"
if [ "${shm_kib:-0}" -lt 524288 ]; then
  shm_flags=(--disable-dev-shm-usage)
  log "note: /dev/shm has ${shm_kib:-0} KiB free; chromium will use /tmp instead"
fi

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
      "${shm_flags[@]}" \
      --window-size="${WIDTH},${HEIGHT}" \
      --lang="${LOCALE}" \
      --user-data-dir="${STATE}/profile" \
      --disk-cache-dir="${STATE}/cache" \
      "${START_URL}"

# `exec`, so runuser, with waypipe under it, is PID 1 from here: when the session
# ends, the instance ends.
# One session per instance is deliberate. waypipe has a `recon` subcommand for
# reattaching a server to a new channel, which would let the browser outlive a
# disconnection, and wiring it up is in TODO.md rather than guessed at here.
