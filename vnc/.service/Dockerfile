# Content-addressed: two packs of the same tree must produce the same image, so the
# base is pinned by digest and every package by its exact version.
#
# The architecture that asks nothing of anybody, and the image shows why: an X
# server that is also the remote-display server, and a browser. Nothing is
# captured from anything, and input arrives through XTEST, which is a userspace
# extension of the X server and needs no kernel input subsystem.
FROM debian:trixie-slim@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132

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
#  chromium                     the browser.
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
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        tigervnc-standalone-server=1.15.0+dfsg-2.1~deb13u1 \
        tigervnc-common=1.15.0+dfsg-2.1~deb13u1 \
        tigervnc-tools=1.15.0+dfsg-2.1~deb13u1 \
        chromium=152.0.7977.82-1~deb13u1 \
        chromium-sandbox=152.0.7977.82-1~deb13u1 \
        x11-utils=7.7+7 \
        fonts-liberation=1:2.1.5-3 \
        fonts-dejavu-core=2.37-8 \
        fonts-noto-cjk=1:20240730+repack1-1 \
        ca-certificates=20250419 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --home-dir /home/browser --shell /usr/sbin/nologin browser \
    && mkdir -p /var/lib/browser /var/log/browser /run/vnc \
    && chown -R browser:browser /var/lib/browser /var/log/browser /run/vnc \
    && chmod 700 /run/vnc

# `./service`, with the dot, and it is not a style choice. The packer sets the
# Docker build context to `.service/` and stages the project under `service/`
# inside it, then rewrites COPY origins that begin with `.` to match. A bare
# `service` is left alone -- so `COPY service /service` reads `.service/service`
# under `nodo pack` and `vnc/service` under `docker build`, and only the second
# one exists in both. PACKING.md says so; this file did not, and the pack failed
# at `chmod: cannot access '/service/entrypoint.sh'` two hundred seconds in.
COPY ./service /service
RUN chmod +x /service/entrypoint.sh
