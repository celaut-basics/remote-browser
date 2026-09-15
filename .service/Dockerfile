# Content-addressed: two packs of the same tree must produce the same image, so the
# base is pinned by digest, every Debian package by its exact version, and the one
# library that comes from git by its commit. That last one is the one that actually
# moves: `git+https://...` with no `@` resolves to whatever the default branch
# happened to be that afternoon, so two packs of an unchanged tree produce two
# different images and a bug seen in a running instance cannot be traced to a
# revision.
#
# Trixie to match the child. Nothing here needs it; having one distribution in the
# repository rather than two is the whole reason.
FROM debian:trixie-slim@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132

# This image holds no browser, no decoder and no Moonlight. It launches the child,
# holds the credentials the child was given, and answers questions about the
# session -- so what it needs is a Python, an HTTP client and the node's own client
# library.
#
#  python3           the runtime. The HTTP API on 8080 is http.server from the
#                    standard library: one endpoint set, three routes, and no
#                    framework to pin, update or audit.
#  python3-requests  the client for Sunshine's API, which is HTTPS with a
#                    self-signed certificate the child generated at boot.
#  python3-pip/git   build-time only, for the line below. Removed afterwards.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        python3=3.13.5-1 \
        python3-requests=2.32.3+dfsg-5+deb13u1 \
        ca-certificates=20250419 \
        python3-pip=25.1.1+dfsg-1 \
        git=1:2.47.3-0+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

# node_controller: StartService, the dependency registry and the instance
# bookkeeping. Pinned to a commit, for the reason in the header.
ARG CELAUT_LIBS_COMMIT=a26891ccf364ea13c5c89dc04568e906958e65ab
RUN pip3 install --no-cache-dir --break-system-packages \
      "git+https://github.com/bee-rpc-protocol/celaut-service-libraries@${CELAUT_LIBS_COMMIT}" \
    && apt-get purge -y python3-pip git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY service /service
RUN chmod +x /service/entrypoint.py
