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
