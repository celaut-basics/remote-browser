# Content-addressed: two packs of the same tree must produce the same image, so the
# base is pinned by digest and every package by its exact version.
#
# The shortest of the three images, and the list is the argument for this
# architecture: there is no X server, no compositor, no video encoder and no
# sound daemon. Chromium is an ordinary Wayland client, and its compositor is the
# one on the user's own machine, reached through waypipe.
FROM debian:trixie-slim@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132

#  chromium   the browser, and the only process that draws anything. Not Chrome:
#             Google publishes no Chrome for linux/arm64.
#  waypipe    the Wayland proxy. It presents a compositor socket Chromium
#             connects to, and translates the protocol's file descriptors --
#             wl_shm pools, the xkb keymap -- into bytes that can cross a kernel
#             boundary, which a raw socket relay cannot do.
#  socat      reverses the direction. waypipe's `server` dials its channel and
#             never listens, while a celaut slot is something a service listens
#             on, so one socat stands between the two. See the entrypoint.
#  fonts-*    a browser with no fonts renders every page as boxes.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        chromium=152.0.7977.82-1~deb13u1 \
        waypipe=0.9.2-1 \
        socat=1.8.0.3-1+deb13u1 \
        fonts-liberation=1:2.1.5-3 \
        fonts-dejavu-core=2.37-8 \
        fonts-noto-cjk=1:20240730+repack1-1 \
        ca-certificates=20250419 \
    && rm -rf /var/lib/apt/lists/*

# Chromium keeps its own sandbox: the guest kernel has CONFIG_USER_NS=y and
# CONFIG_SECCOMP_FILTER=y, so every layer it wants is available, and this is the
# one service on the network whose job is to open pages nobody vetted.
RUN useradd --create-home --home-dir /home/browser --shell /usr/sbin/nologin browser \
    && mkdir -p /var/lib/browser /var/log/browser /run/waypipe /run/user/1000 \
    && chown -R browser:browser /var/lib/browser /var/log/browser /run/waypipe /run/user/1000 \
    && chmod 700 /run/user/1000

COPY service /service
RUN chmod +x /service/entrypoint.sh
