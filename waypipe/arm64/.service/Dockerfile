# Content-addressed: two packs of the same tree must produce the same image, so the
# base is pinned by digest and every package by its exact version.
#
# The shortest of the three images, and the list is the argument for this
# architecture: there is no X server, no compositor, no video encoder and no
# sound daemon. Chromium is an ordinary Wayland client, and its compositor is the
# one on the user's own machine, reached through waypipe.
#
# No line below names an architecture. The base digest is a multi-arch index and
# every pin exists, at the same version, for linux/arm64 and linux/amd64. The pack roots
# amd64/ and arm64/ hold this same file. Only `architecture` in service.json differs.
FROM debian:trixie-slim@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132

# apt reads a frozen snapshot of the Debian archive, not the live mirror. The live
# mirror drops a Chromium version a few weeks after it is published, and an exact
# pin then fails in apt. See the same block in vnc/.service/Dockerfile. To update,
# change DEBIAN_SNAPSHOT and the pins together, in all three images.
ARG DEBIAN_SNAPSHOT=20261004T000000Z
RUN sed -i \
      -e "s|^URIs: http://deb.debian.org/debian\$|URIs: http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|" \
      -e "s|^URIs: http://deb.debian.org/debian-security\$|URIs: http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
      -e '/^URIs: /a Check-Valid-Until: no' \
      /etc/apt/sources.list.d/debian.sources \
    && [ "$(grep -c '^URIs: http://snapshot.debian.org/' /etc/apt/sources.list.d/debian.sources)" = 2 ]

#  chromium, chromium-common
#             the browser, and the only process that draws anything. Not Chrome:
#             Google publishes no Chrome for linux/arm64. The two are pinned
#             together: chromium depends on exactly its own version of
#             chromium-common, so a pin on one alone fails in apt.
#  chromium-sandbox
#             the setuid helper the sandbox actually is. It is a *Recommends* of
#             chromium and --no-install-recommends is above, so without naming it
#             the image has no sandbox binary -- and Chromium exits 1 rather than
#             warning and carrying on.
#  waypipe    the Wayland proxy. It presents a compositor socket Chromium
#             connects to, and translates the protocol's file descriptors --
#             wl_shm pools, the xkb keymap -- into bytes that can cross a kernel
#             boundary, which a raw socket relay cannot do.
#  socat      reverses the direction. waypipe's `server` dials its channel and
#             never listens, while a celaut slot is something a service listens
#             on, so one socat stands between the two. See the entrypoint.
#  fonts-*    a browser with no fonts renders every page as boxes.
#  ca-certificates
#             the web is TLS. Without this every https:// page fails to load.
#  tzdata     zoneinfo files. The entrypoint checks TIMEZONE against
#             /usr/share/zoneinfo. libc6 only Recommends tzdata, and
#             --no-install-recommends would omit it if the base image did not
#             already install it. Default TIMEZONE is UTC.
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y \
        chromium=154.0.8037.92-1~deb13u1 \
        chromium-common=154.0.8037.92-1~deb13u1 \
        chromium-sandbox=154.0.8037.92-1~deb13u1 \
        waypipe=0.9.2-1 \
        socat=1.8.0.3-1+deb13u1 \
        fonts-liberation=1:2.1.5-3 \
        fonts-dejavu-core=2.37-8 \
        fonts-noto-cjk=1:20240730+repack1-1 \
        ca-certificates=20250419 \
        tzdata=2026c-0+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

# Chromium keeps its own sandbox: the guest kernel has CONFIG_USER_NS=y and
# CONFIG_SECCOMP_FILTER=y, so every layer it wants is available, and this is the
# one service on the network whose job is to open pages nobody vetted.
#
# /run/waypipe and /run/user/1000 are not made here: /run is a tmpfs in the guest,
# so the entrypoint makes them at boot (issue #2).
RUN useradd --create-home --home-dir /home/browser --shell /usr/sbin/nologin browser \
    && mkdir -p /var/lib/browser /var/log/browser \
    && chown -R browser:browser /var/lib/browser /var/log/browser

# `./service`, with the dot: the packer rewrites COPY origins beginning with `.`
# to the `service/` subtree it stages inside the `.service/` build context, and
# leaves bare relative origins alone. See PACKING.md, and the same line in the
# other two images.
COPY ./service /service
RUN chmod +x /service/entrypoint.sh
