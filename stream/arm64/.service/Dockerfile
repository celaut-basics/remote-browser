# Content-addressed: two packs of the same tree must produce the same image, so the
# base is pinned by digest and every package by its exact version. What this image
# decides -- which browser, which encoder, which preset -- is visible in the digest
# of the service, and a build that drifted underneath it would change the stream
# without changing the hash anyone reviewed.
#
# Trixie, not bookworm, and for one reason: Sunshine publishes a Debian package for
# trixie and not for bookworm. Everything else in here exists on both.
#
# No line below names an architecture. The base digest is a multi-arch index, every
# Debian pin exists at the same version for linux/arm64 and linux/amd64, and the
# Sunshine package is chosen by the architecture of the image being built. The pack roots
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

# Every version is the one in the snapshot above. Pinned to the patch, not to the
# suite: a security update should not silently change this image.
#
# pulseaudio is `17.0+dfsg1-2+b1`, which is not the version packages.debian.org
# shows. The `+b1` is a binNMU -- a rebuild of the same source against a changed
# dependency, given a binary-only version suffix. `apt-get install pkg=<source
# version>` fails outright, so this pin has to be read off the Packages index of
# the target architecture, not off the archive's source page. In September it was
# `+b1` on arm64 only; in the snapshot it is `+b1` on both.
#
#  chromium        the browser. Not Chrome: Google ships no Chrome for linux/arm64,
#                  so on this architecture Chromium is not a substitution, it is the
#                  only build that exists.
#  chromium-common pinned together with chromium: chromium depends on exactly its own
#                  version of chromium-common, so a pin on one alone fails in apt.
#  chromium-sandbox the setuid helper that the sandbox actually is. Debian makes it
#                  a *Recommends* of chromium, and --no-install-recommends is on the
#                  line below, so leaving it unnamed silently produces an image with
#                  no sandbox binary in it. Chromium does not fall back: it exits 1
#                  with "No usable sandbox!" before it opens a window.
#  xvfb            the X server. There is no display of any kind in a nodo microVM
#                  (# CONFIG_DRM is not set, # CONFIG_FB is not set in the guest
#                  kernel), so the framebuffer has to be one the X server allocates
#                  in ordinary memory. Xvfb needs no VT, which is what makes it the
#                  one X server that runs here -- see NODE-REQUIREMENTS.md. It also
#                  has the XTEST extension, which is how Sunshine injects keyboard
#                  and mouse when the guest has no /dev/uinput.
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
#  tzdata          zoneinfo files. The entrypoint checks TIMEZONE against
#                  /usr/share/zoneinfo. libc6 only Recommends tzdata, and
#                  --no-install-recommends would omit it if the base image did
#                  not already install it. Default TIMEZONE is UTC.
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y \
        chromium=154.0.8037.92-1~deb13u1 \
        chromium-common=154.0.8037.92-1~deb13u1 \
        chromium-sandbox=154.0.8037.92-1~deb13u1 \
        xvfb=2:21.1.16-1.3+deb13u4 \
        x11-utils=7.7+7 \
        pulseaudio=17.0+dfsg1-2+b1 \
        fonts-liberation=1:2.1.5-3 \
        fonts-dejavu-core=2.37-8 \
        fonts-noto-cjk=1:20240730+repack1-1 \
        ca-certificates=20250419 \
        tzdata=2026c-0+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

# Sunshine, pinned by version AND by the sha256 GitHub publishes for each asset.
# It is not in Debian, so it arrives over the network at build time -- which is
# exactly the input that has to be nailed down for the image to stay reproducible.
# apt resolves its dependencies from the same snapshot as everything above.
#
# The asset is chosen by `dpkg --print-architecture`, which is the architecture of
# the image being built, not of the build host. That works under `nodo pack` and
# under a plain `docker build` alike, and an architecture with no digest here stops
# the build rather than installing an unchecked package.
#
# curl is installed for the download and purged in the same layer, so it is not in
# the image. Sunshine links libcurl, not the curl program, so the purge leaves its
# dependencies in place.
#
# GPL-3.0. It is the GameStream host: it captures the X display, encodes it, and
# speaks the protocol Moonlight speaks.
ARG SUNSHINE_VERSION=2026.914.233613
ARG SUNSHINE_SHA256_ARM64=45f250a6bae3629bd67d6856356e5d838569fbe4f6128440124c727a3d5fef5e
ARG SUNSHINE_SHA256_AMD64=a86f858cbae57f60ecebd445402ee0295c1c057b857bd45d44c2ea2d255cbbfb
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
         arm64) sha="$SUNSHINE_SHA256_ARM64" ;; \
         amd64) sha="$SUNSHINE_SHA256_AMD64" ;; \
         *) echo "no pinned Sunshine package for $arch" >&2; exit 1 ;; \
       esac \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y \
        curl=8.14.1-2+deb13u5 \
    && curl -fsSL --retry 5 -o /tmp/sunshine.deb \
      "https://github.com/LizardByte/Sunshine/releases/download/v${SUNSHINE_VERSION}/sunshine_${SUNSHINE_VERSION}-1%2Bdebiantrixie_${arch}.deb" \
    && echo "${sha}  /tmp/sunshine.deb" | sha256sum -c - \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y /tmp/sunshine.deb \
    && apt-get purge -y --auto-remove curl \
    && command -v sunshine >/dev/null \
    && rm -f /tmp/sunshine.deb \
    && rm -rf /var/lib/apt/lists/*

# Chromium refuses to run as root with its sandbox on, and the sandbox is worth
# keeping: the guest kernel has CONFIG_USER_NS=y and CONFIG_SECCOMP_FILTER=y, so
# every layer Chromium wants is available. Running it as root with --no-sandbox
# would throw away a real boundary to save one useradd, inside the one service on
# the network whose whole job is to open untrusted pages.
#
# /run/pulse is not made here: /run is a tmpfs in the guest, so the entrypoint
# makes it at boot (issue #2).
RUN useradd --create-home --home-dir /home/browser --shell /usr/sbin/nologin browser \
    && mkdir -p /var/lib/browser /var/log/browser \
    && chown -R browser:browser /var/lib/browser /home/browser

# `./service`, with the dot: the packer rewrites COPY origins beginning with `.`
# to the `service/` subtree it stages inside the `.service/` build context, and
# leaves bare relative origins alone. See PACKING.md, and the same line in the
# other two images.
COPY ./service /service
RUN chmod +x /service/entrypoint.sh
