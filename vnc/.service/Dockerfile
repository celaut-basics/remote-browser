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
#  tigervnc-common              vncpasswd, which writes the obfuscated password
#                               file Xvnc reads.
#  chromium                     the browser.
#  x11-utils                    xdpyinfo, so the entrypoint waits for the display
#                               to answer instead of sleeping and hoping.
#  fonts-*                      a browser with no fonts renders every page as
#                               boxes.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        tigervnc-standalone-server=1.15.0+dfsg-2.1~deb13u1 \
        tigervnc-common=1.15.0+dfsg-2.1~deb13u1 \
        chromium=152.0.7977.82-1~deb13u1 \
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

COPY service /service
RUN chmod +x /service/entrypoint.sh
