# Content-addressed: two packs of the same tree must produce the same image, so the
# base is pinned by digest and every package by its exact version.
#
# The architecture that asks nothing of anybody, and the image shows why: an X
# server that is also the remote-display server, and a browser. Nothing is
# captured from anything, and input arrives through XTEST, which is a userspace
# extension of the X server and needs no kernel input subsystem.
#
# No line below names an architecture. The base digest is a multi-arch index and
# every pin exists, at the same version, for linux/arm64 and linux/amd64. The pack roots
# amd64/ and arm64/ hold this same file. Only `architecture` in service.json differs.
FROM debian:trixie-slim@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132

# apt reads a frozen snapshot of the Debian archive, not the live mirror.
#
# The live mirror keeps one version of each package per suite, and the security
# suite replaces Chromium every few weeks. So an exact pin against the live mirror
# stops resolving soon after it is written: 152.0.7977.82 went in September, then
# 153.0.8010.52, and every image in this repository failed in apt each time.
# snapshot.debian.org keeps every state of the archive at a fixed URL, so the pins
# below resolve for as long as the snapshot service exists. To update, change
# DEBIAN_SNAPSHOT and the pins together, in all three images.
#
# Check-Valid-Until is off because a Release file in a snapshot is old by design.
# The signatures are still checked. The guard after sed stops the build if the
# base image changes the layout of its sources file, so the build cannot fall back
# to the live mirror without notice.
ARG DEBIAN_SNAPSHOT=20261004T000000Z
RUN sed -i \
      -e "s|^URIs: http://deb.debian.org/debian\$|URIs: http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|" \
      -e "s|^URIs: http://deb.debian.org/debian-security\$|URIs: http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
      -e '/^URIs: /a Check-Valid-Until: no' \
      /etc/apt/sources.list.d/debian.sources \
    && [ "$(grep -c '^URIs: http://snapshot.debian.org/' /etc/apt/sources.list.d/debian.sources)" = 2 ]

#  tigervnc-standalone-server   Xvnc: one process that is the X server AND the RFB
#                               server. There is no Xvfb here and no separate
#                               x11vnc attaching to it -- the framebuffer Xvnc
#                               allocates is the one it serves.
#  tigervnc-common              the alternatives group Xvnc resolves through, and
#                               the PAM and config files the server expects.
#  tigervnc-tools               vncpasswd, which writes the obfuscated password
#                               file Xvnc reads. NOT tigervnc-common: that ships
#                               one binary, tigervncconfig, and nothing else.
#                               Confirmed against the image, not the description.
#  chromium, chromium-common    the browser. The two are pinned together:
#                               chromium depends on exactly its own version of
#                               chromium-common, so a pin on one alone fails in
#                               apt.
#  chromium-sandbox             the setuid helper the sandbox is. It is a
#                               *Recommends* of chromium, and --no-install-recommends
#                               is above, so without naming it here the image has no
#                               sandbox binary -- and Chromium does not warn and
#                               continue, it exits 1 before opening a window. Keeping
#                               the sandbox is what this repository says it does.
#  x11-utils                    xdpyinfo, so the entrypoint waits for the display
#                               to answer instead of sleeping and hoping.
#  fonts-*                      a browser with no fonts renders every page as
#                               boxes.
#  ca-certificates              the web is TLS. Without this every https:// page
#                               fails to load.
#  tzdata                       zoneinfo files. The entrypoint checks TIMEZONE
#                               against /usr/share/zoneinfo. libc6 only
#                               Recommends tzdata, and --no-install-recommends
#                               would omit it if the base image did not already
#                               install it. Default TIMEZONE is UTC.
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y \
        tigervnc-standalone-server=1.15.0+dfsg-2.1~deb13u1 \
        tigervnc-common=1.15.0+dfsg-2.1~deb13u1 \
        tigervnc-tools=1.15.0+dfsg-2.1~deb13u1 \
        chromium=154.0.8037.92-1~deb13u1 \
        chromium-common=154.0.8037.92-1~deb13u1 \
        chromium-sandbox=154.0.8037.92-1~deb13u1 \
        x11-utils=7.7+7 \
        fonts-liberation=1:2.1.5-3 \
        fonts-dejavu-core=2.37-8 \
        fonts-noto-cjk=1:20240730+repack1-1 \
        ca-certificates=20250419 \
        tzdata=2026c-0+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

# /run/vnc is not made here: /run is a tmpfs in the guest, so the entrypoint makes
# it at boot (issue #2).
RUN useradd --create-home --home-dir /home/browser --shell /usr/sbin/nologin browser \
    && mkdir -p /var/lib/browser /var/log/browser \
    && chown -R browser:browser /var/lib/browser /var/log/browser

# `./service`, with the dot, and it is not a style choice. The packer sets the
# Docker build context to `.service/` and stages the project under `service/`
# inside it, then rewrites COPY origins that begin with `.` to match. A bare
# `service` is left alone -- so `COPY service /service` reads `.service/service`
# under `nodo pack` and `vnc/service` under `docker build`, and only the second
# one exists in both. PACKING.md says so; this file did not, and the pack failed
# at `chmod: cannot access '/service/entrypoint.sh'` two hundred seconds in.
COPY ./service /service
RUN chmod +x /service/entrypoint.sh
