# Content-addressed: two packs of the same tree must produce the same image, so the
# base is pinned by digest and every package by its exact version. What this image
# decides -- which browser, which encoder, which preset -- is visible in the digest
# of the service, and a build that drifted underneath it would change the stream
# without changing the hash anyone reviewed.
#
# Trixie, not bookworm, and for one reason: Sunshine publishes a Debian package for
# trixie and not for bookworm. Everything else in here exists on both.
FROM debian:trixie-slim@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132

# Every version is the one in trixie on 2026-09-15. Pinned to the patch, not to the
# suite: a security update should not silently change this image. The price is that
# the build stops -- when a version leaves the mirror -- until this file is edited,
# which is a price paid on purpose.
#
# And one of these is not the version packages.debian.org shows, which is the trap
# in reading the archive rather than the image: pulseaudio is `17.0+dfsg1-2+b1` on
# arm64 and `17.0+dfsg1-2` on amd64. The `+b1` is a binNMU -- a rebuild of the same
# source against a changed dependency, given a binary-only version suffix on the
# architectures it was rebuilt for. `apt-get install pkg=<source version>` fails
# outright there, so this line is the one that has to be read off the target
# architecture and cannot be read off the archive at all. Every other pin above is
# identical on both.
#
#  chromium        the browser. Not Chrome: Google ships no Chrome for linux/arm64,
#                  so on this architecture Chromium is not a substitution, it is the
#                  only build that exists.
#  chromium-sandbox the setuid helper that the sandbox actually is. Debian makes it
#                  a *Recommends* of chromium, and --no-install-recommends is on the
#                  line below, so leaving it unnamed silently produces an image with
#                  no sandbox binary in it. Chromium does not fall back: it exits 1
#                  with "No usable sandbox!" before it opens a window.
#  xvfb            the X server. There is no display of any kind in a nodo microVM
#                  (# CONFIG_DRM is not set, # CONFIG_FB is not set in the guest
#                  kernel), so the framebuffer has to be one the X server allocates
#                  in ordinary memory. Xvfb needs no VT, which is what makes it the
#                  one X server that runs here -- see NODE-REQUIREMENTS.md.
#  x11-utils       xdpyinfo, so the entrypoint can wait for the display to answer
#                  instead of sleeping and hoping.
#  pulseaudio      a *userspace* null sink. The guest kernel has
#                  # CONFIG_SOUND is not set, so there is no ALSA device to open --
#                  but module-null-sink never touches one, and its monitor source is
#                  a perfectly good thing for Sunshine to encode. Audio is the one
#                  capability here that needs nothing from the node.
#  fonts-*         a browser with no fonts renders every page as boxes. Liberation
#                  covers Latin, DejaVu the rest of the European coverage, Noto CJK
#                  the scripts neither has.
#  ca-certificates the web is TLS. Without this every https:// page fails to load.
#  curl            fetches the Sunshine package below, and nothing at runtime.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        chromium=152.0.7977.82-1~deb13u1 \
        chromium-sandbox=152.0.7977.82-1~deb13u1 \
        xvfb=2:21.1.16-1.3+deb13u4 \
        x11-utils=7.7+7 \
        pulseaudio=17.0+dfsg1-2+b1 \
        fonts-liberation=1:2.1.5-3 \
        fonts-dejavu-core=2.37-8 \
        fonts-noto-cjk=1:20240730+repack1-1 \
        ca-certificates=20250419 \
        curl=8.14.1-2+deb13u5 \
    && rm -rf /var/lib/apt/lists/*

# Sunshine, pinned by version AND by the sha256 GitHub publishes for that asset.
# It is not in Debian, so it arrives over the network at build time -- which is
# exactly the input that has to be nailed down for the image to stay reproducible.
# apt resolves its dependencies from the same pinned suite as everything above.
#
# GPL-3.0. It is the GameStream host: it captures the X display, encodes it, and
# speaks the protocol Moonlight speaks.
ARG SUNSHINE_VERSION=2026.914.233613
ARG SUNSHINE_SHA256=45f250a6bae3629bd67d6856356e5d838569fbe4f6128440124c727a3d5fef5e
RUN curl -fsSL -o /tmp/sunshine.deb \
      "https://github.com/LizardByte/Sunshine/releases/download/v${SUNSHINE_VERSION}/sunshine_${SUNSHINE_VERSION}-1%2Bdebiantrixie_arm64.deb" \
    && echo "${SUNSHINE_SHA256}  /tmp/sunshine.deb" | sha256sum -c - \
    && apt-get update \
    && apt-get install --no-install-recommends -y /tmp/sunshine.deb \
    && rm -f /tmp/sunshine.deb \
    && rm -rf /var/lib/apt/lists/*

# Chromium refuses to run as root with its sandbox on, and the sandbox is worth
# keeping: the guest kernel has CONFIG_USER_NS=y and CONFIG_SECCOMP_FILTER=y, so
# every layer Chromium wants is available. Running it as root with --no-sandbox
# would throw away a real boundary to save one useradd, inside the one service on
# the network whose whole job is to open untrusted pages.
RUN useradd --create-home --home-dir /home/browser --shell /usr/sbin/nologin browser \
    && mkdir -p /var/lib/browser /var/log/browser /run/pulse \
    && chown -R browser:browser /var/lib/browser /home/browser

# `./service`, with the dot: the packer rewrites COPY origins beginning with `.`
# to the `service/` subtree it stages inside the `.service/` build context, and
# leaves bare relative origins alone. See PACKING.md, and the same line in the
# other two images.
COPY ./service /service
RUN chmod +x /service/entrypoint.sh
