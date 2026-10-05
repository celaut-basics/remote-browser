# shellcheck shell=bash
# Checks for the values that a launcher gives with `nodo execute -e`.
#
# The same file is in vnc/, waypipe/ and stream/. Each service packs only its
# own directory, so this file is copied and not shared. tests/ checks that the
# three copies are equal.
#
# The entrypoint defines fail() before it reads this file. Each check stops the
# instance with a clear message. A bad value must not go on to a command line or
# to a configuration file, where it fails later in a log, or does not fail.

# need_int NAME VALUE MIN MAX
need_int() {
  [[ "$2" =~ ^[1-9][0-9]{0,4}$ ]] && [ "$2" -ge "$3" ] && [ "$2" -le "$4" ] \
    || fail "$1 must be an integer from $3 to $4, got '$2'"
}

# need_one_of NAME VALUE CHOICE...
need_one_of() {
  local name="$1" value="$2" choice
  shift 2
  for choice in "$@"; do
    [ "$value" = "$choice" ] && return 0
  done
  fail "$name must be one of: $*. Got '$value'"
}

# check_browser_values: WIDTH, HEIGHT, START_URL, LOCALE and TIMEZONE.
#
# START_URL is the last argument to Chromium. A value that starts with `-` is
# a Chromium switch, for example --remote-debugging-port, so it is refused.
# TIMEZONE must name a file in the zone database. The pattern refuses `..`, so
# the name cannot point out of that directory.
check_browser_values() {
  need_int WIDTH "$WIDTH" 320 7680
  need_int HEIGHT "$HEIGHT" 240 4320
  [[ "$START_URL" != -* ]] || fail "START_URL must not start with '-', got '$START_URL'"
  [[ "$LOCALE" =~ ^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$ ]] \
    || fail "LOCALE must be a language tag such as en-US, got '$LOCALE'"
  [[ "$TIMEZONE" =~ ^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$ ]] \
    && [ -f "${ZONEINFO:-/usr/share/zoneinfo}/$TIMEZONE" ] \
    || fail "TIMEZONE must be a zone name such as Europe/Madrid, got '$TIMEZONE'"
}

# resolv_conf_for SERVERS: write resolv.conf lines for a list of IPv4
# addresses to stdout. Commas or spaces separate the addresses. glibc reads
# the first three nameserver lines only, so more than three is an error.
resolv_conf_for() {
  local servers server octet
  read -r -a servers <<<"${1//,/ }"
  [ "${#servers[@]}" -ge 1 ] || fail "DNS_SERVERS names no server"
  [ "${#servers[@]}" -le 3 ] || fail "DNS_SERVERS names ${#servers[@]} servers; the limit is 3"
  for server in "${servers[@]}"; do
    [[ "$server" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] \
      || fail "DNS_SERVERS: '$server' is not an IPv4 address"
    for octet in ${server//./ }; do
      [ "$((10#$octet))" -le 255 ] || fail "DNS_SERVERS: '$server' is not an IPv4 address"
    done
    printf 'nameserver %s\n' "$server"
  done
}

# set_dns SERVERS [FILE]: the name servers of this guest.
#
# nodo does not serve DNS to a guest and does not write resolv.conf
# (src/virtualizers/microvm/network.py in nodo). The guest keeps the file of
# the image. In debian:trixie-slim that file names 1.1.1.1 and 1.0.0.1. These
# services declare the `*` network, so they can reach those servers on port 53.
#
# DNS_SERVERS replaces that list, because the resolver sees each name that the
# browser looks up. The file is written in place and not replaced with mv:
# under Docker it is a mount point, and mv onto a mount point fails.
set_dns() {
  local file="${2:-/etc/resolv.conf}" lines
  if [ -n "$1" ]; then
    lines="$(resolv_conf_for "$1")" || exit 1
    printf '%s\n' "$lines" >"$file"
  elif ! grep -q '^nameserver ' "$file" 2>/dev/null; then
    printf 'nameserver %s\n' 1.1.1.1 1.0.0.1 >"$file"
  fi
}

# node_address [ROUTE_FILE]: the IPv4 address of the default gateway.
#
# In a nodo guest the default gateway is the node's address on the bridge.
# The initramfs sets it from the `ip=` kernel parameter. The node also opens
# each `nodo tunnel` connection to a slot from this address
# (src/tunneling/rpc_tunnel.py in nodo). /proc/net/route gives the address in
# host byte order, which is little-endian on amd64 and on arm64.
node_address() {
  local hex
  hex="$(awk '$2 == "00000000" && $3 != "00000000" { print $3; exit }' "${1:-/proc/net/route}")"
  [[ "$hex" =~ ^[0-9A-Fa-f]{8}$ ]] || return 1
  printf '%d.%d.%d.%d\n' "0x${hex:6:2}" "0x${hex:4:2}" "0x${hex:2:2}" "0x${hex:0:2}"
}
