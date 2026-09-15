#!/usr/bin/env python3
"""PID 1 of the remote-browser viewer.

It launches the browser child, holds the credentials that child was given, brokers
the one pairing step a GameStream client needs, and reports where the session is.

What it does not do, yet, is draw. Not because a guest cannot reach a display --
it can, over a declared slot with the host connecting in, which is how every other
service on this network is reached -- but because the only display protocol that
survives the trip carries decoded frames, and re-shipping uncompressed video
across a bridge inside one machine to deliver pixels that already crossed the
network compressed is a thing to do on purpose or not at all.

What a guest genuinely cannot do is dial *out* to a display: `*` egress is written
on the FORWARD hook and the host's own addresses are matched on INPUT, virtiofs
does not carry AF_UNIX, and the VM has no vsock device. NODE-REQUIREMENTS.md §2
has both halves, and everything below is what makes collecting the stream from a
Moonlight on the host one command instead of six.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import child as child_mod  # noqa: E402
import config as config_mod  # noqa: E402
from sunshine import Sunshine, SunshineError  # noqa: E402

LISTEN_PORT = 8080

# GameStream's ports, as Sunshine derives them from its base. They are here rather
# than in the child's spec alone because the viewer has to name them to say where a
# session is, and a second copy that could drift would be worse than a constant.
HTTP_PORT, HTTPS_PORT, WEB_PORT, RTSP_PORT = 47989, 47984, 47990, 48010
UDP_PORTS = (47998, 47999, 48000, 48002)


class Session:
    """Everything one launch of the child produced. Guarded because /pair races /health."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.child: Optional[child_mod.Child] = None
        self.admin_user = ""
        self.admin_pass = ""
        self.settings: Optional[config_mod.Settings] = None
        self.node_url = ""
        self.error: Optional[str] = None

    def describe(self) -> dict:
        with self.lock:
            if self.error:
                return {"state": "failed", "error": self.error}
            if self.child is None:
                return {"state": "starting"}
            slots = self.child.slots()
            offsets_ok = self.child.offsets_survived()
            http = slots.get(HTTP_PORT)
            return {
                "state": "running",
                "browser": {
                    "instance_token": self.child.token,
                    "slots": {str(k): f"{v[0]}:{v[1]}" for k, v in sorted(slots.items())},
                    "gamestream_host": f"{http[0]}:{http[1]}" if http else None,
                },
                "settings": {
                    "start_url": self.settings.start_url,
                    "resolution": f"{self.settings.width}x{self.settings.height}",
                    "fps": self.settings.fps,
                    "sw_preset": self.settings.sw_preset,
                },
                "pairing": {
                    "how": "point a GameStream client at gamestream_host, take the PIN it "
                           "shows you, and POST it here: {\"pin\": \"1234\"} to /pair",
                    "why": "the administrator password for the child's Sunshine stays in "
                           "this instance and is never published",
                },
                "caveats": _caveats(offsets_ok),
            }


def _caveats(offsets_ok: bool) -> list:
    caveats = [
        "VIEW-ONLY unless the node's guest kernel has CONFIG_INPUT + CONFIG_INPUT_UINPUT: "
        "Sunshine injects keyboard and mouse through /dev/uinput, and nodo's guest kernel "
        "is built with '# CONFIG_INPUT is not set'. See NODE-REQUIREMENTS.md.",
        "The stream is encoded on a CPU. celaut.Sysresources has no field for an "
        "accelerator, so no service on this network can ask a node for one.",
    ]
    if not offsets_ok:
        caveats.append(
            "The node published these slots on ports from its own free-port range, so "
            "GameStream's fixed offsets between them did not survive. A client pointed at "
            "gamestream_host will compute the wrong ports for video, audio and control. "
            "Rebuild the family locally instead: one `nodo tunnel <token> <slot> --listen "
            "<same slot>` per port, `--udp` for the datagram ones."
        )
    return caveats


SESSION = Session()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003 - BaseHTTPRequestHandler's own name
        logging.info("http: " + fmt, *args)

    def _reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - the name the base class dispatches on
        if self.path in ("/", "/session"):
            self._reply(200, SESSION.describe())
        elif self.path == "/health":
            described = SESSION.describe()
            self._reply(200 if described["state"] == "running" else 503, described)
        else:
            self._reply(404, {"error": f"no route {self.path}"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/pair":
            self._reply(404, {"error": f"no route {self.path}"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self._reply(400, {"error": "body must be JSON"})
            return

        pin = str(payload.get("pin") or "").strip()
        name = str(payload.get("name") or "moonlight").strip()
        pairing_id = payload.get("pairing_id")

        with SESSION.lock:
            child = SESSION.child
            user, password = SESSION.admin_user, SESSION.admin_pass
        if child is None:
            self._reply(503, {"error": "no child is running"})
            return
        address = child.slot(WEB_PORT)
        if address is None:
            self._reply(503, {"error": f"the node published no address for slot {WEB_PORT}"})
            return

        try:
            result = Sunshine(address, user, password).apply_pin(pin, name, pairing_id)
        except SunshineError as exc:
            self._reply(502, {"error": str(exc)})
            return
        self._reply(200, {"paired": True, "sunshine": result})


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        configuration = config_mod.load_config()
        node_url = config_mod.gateway_url(configuration)
        settings = config_mod.resolve(config_mod.merged_env(configuration))
        browser_hash = config_mod.find_dependency_hash("BROWSER")
    except config_mod.ConfigError as exc:
        logging.error("%s", exc)
        return 1

    # One password per session, generated here and never written to disk. It is not
    # in the child's image, so it is not in the child's content hash, so two
    # instances of the same digest do not share it.
    admin_user = "nodo"
    admin_pass = secrets.token_urlsafe(24)

    logging.info(
        "launching browser child %s (%dx%d@%d, preset=%s)",
        browser_hash[:16], settings.width, settings.height, settings.fps, settings.sw_preset,
    )

    try:
        child = child_mod.launch(
            node_url=node_url,
            service_hash=browser_hash,
            environment=settings.child_environment(admin_user, admin_pass),
            initial_mu=settings.child_initial_mu,
        )
    except child_mod.ChildLaunchError as exc:
        logging.error("%s", exc)
        return 1

    http_address = child.slot(HTTP_PORT)
    if http_address is None:
        logging.error(
            "the node published no address for the child's slot %d; without it there is "
            "nothing to connect a client to. Reach it with `nodo tunnel` instead.", HTTP_PORT,
        )
        child_mod.release(node_url, child)
        return 1

    try:
        child_mod.wait_until_ready(http_address, settings.child_ready_timeout_s)
    except child_mod.ChildNotReadyError as exc:
        logging.error("%s", exc)
        child_mod.release(node_url, child)
        return 1

    with SESSION.lock:
        SESSION.child = child
        SESSION.admin_user, SESSION.admin_pass = admin_user, admin_pass
        SESSION.settings = settings
        SESSION.node_url = node_url

    if not child.offsets_survived():
        logging.warning(
            "the node remapped the child's ports, so GameStream's offsets did not survive; "
            "/session says what to do about it"
        )

    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)

    def shutdown(signum, _frame):
        logging.info("signal %s: stopping the child and closing", signum)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    logging.info("session ready; API on :%d, browser at %s:%s", LISTEN_PORT, *http_address)
    try:
        server.serve_forever()
    finally:
        child_mod.release(node_url, child)
    return 0


if __name__ == "__main__":
    sys.exit(main())
