#!/usr/bin/env python3
"""What this instance was launched with, and where its dependency lives.

Two sources, and they are not interchangeable. ``/__config__`` is a
``celaut.ConfigurationFile`` the node wrote: the gateway to call, and the
environment variables whoever launched this instance chose. ``.dependencies`` is
written into the package at pack time by ``dependencies_env``, and holds the
content hash of the browser child -- so this service asks its node for a service
by digest, never by name.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# Guarded so the settings logic below can be exercised without the node's client
# library present -- see tests/. Everything that actually needs protobuf says so at
# the point of use, rather than failing at import with a stack trace that points at
# the wrong problem.
try:
    from node_controller.gateway.protos import celaut_pb2
except ImportError:  # pragma: no cover - present in the image, absent under test
    celaut_pb2 = None


def _require_protos():
    if celaut_pb2 is None:
        raise ConfigError(
            "node_controller is not importable: this package was built without the "
            "client library, so it cannot read /__config__ or launch anything"
        )
    return celaut_pb2

CONFIG_PATH = "/__config__"

# Where the packer may have put the two files this service reads. Nothing in
# `pack_config.json` fixes them relative to the entrypoint, and a wrong guess here
# fails as "no such service" much later, so all the plausible roots are tried and
# the one that answered is logged.
_SEARCH_ROOTS = ("/", os.path.dirname(os.path.abspath(__file__)), os.getcwd())


class ConfigError(Exception):
    """The instance cannot be configured, and starting anyway would be worse."""


def load_config(path: str = CONFIG_PATH) -> "celaut_pb2.ConfigurationFile":
    protos = _require_protos()
    if not os.path.isfile(path):
        raise ConfigError(f"{path} is missing: this process is not running as a celaut service")
    config = protos.ConfigurationFile()
    with open(path, "rb") as handle:
        config.ParseFromString(handle.read())
    return config


def gateway_url(config: "celaut_pb2.ConfigurationFile") -> str:
    for uri_slot in config.gateway.uri_slot:
        for uri in uri_slot.uri:
            if uri.ip and uri.port:
                return f"{uri.ip}:{uri.port}"
    raise ConfigError("no gateway URI in /__config__: there is nothing to launch a child through")


def merged_env(config: "celaut_pb2.ConfigurationFile") -> Dict[str, str]:
    """``Configuration.environment_variables``, with the process environment on top.

    Process wins so a shell test can override one value without rebuilding a
    configuration file for it.
    """
    env: Dict[str, str] = {
        key: value.decode("utf-8", errors="replace")
        for key, value in config.config.environment_variables.items()
    }
    env.update({k: v for k, v in os.environ.items() if v is not None})
    return env


def find_dependency_hash(name: str = "BROWSER") -> str:
    """The child's content hash, out of the ``.dependencies`` file.

    ``dependencies_env: true`` writes one ``KEY=<sha3-256 hex>`` line per entry of
    ``pack_config.json``. Addressing the child by that digest rather than by a tag
    is what makes a session reproducible and what makes swapping the browser a
    visible diff instead of a silent change of behaviour.
    """
    tried = []
    for root in _SEARCH_ROOTS:
        path = os.path.join(root, ".dependencies")
        tried.append(path)
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                if sep and key == name and value:
                    return value
    raise ConfigError(
        f"no '{name}' entry in any .dependencies file (looked in {', '.join(tried)}). "
        "The package was built without its child, so there is nothing to launch."
    )


@dataclass(frozen=True)
class Settings:
    start_url: str
    width: int
    height: int
    fps: int
    sw_preset: str
    locale: str
    timezone: str
    child_ready_timeout_s: int
    child_initial_mu: Optional[int]

    def child_environment(self, admin_user: str, admin_pass: str) -> Dict[str, bytes]:
        """What the child is launched with.

        The credentials are generated per session and passed here, which is the
        point of the parent holding them: they are never written into the child's
        image, so they are not part of its content hash, and two sessions of the
        same digest do not share an administrator password.
        """
        return {
            "START_URL": self.start_url.encode(),
            "WIDTH": str(self.width).encode(),
            "HEIGHT": str(self.height).encode(),
            "FPS": str(self.fps).encode(),
            "SW_PRESET": self.sw_preset.encode(),
            "LOCALE": self.locale.encode(),
            "TIMEZONE": self.timezone.encode(),
            "ADMIN_USER": admin_user.encode(),
            "ADMIN_PASS": admin_pass.encode(),
        }


_PRESETS = (
    "ultrafast", "superfast", "veryfast", "faster",
    "fast", "medium", "slow", "slower", "veryslow",
)


def _int(env: Dict[str, str], key: str, default: int) -> int:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def resolve(env: Dict[str, str]) -> Settings:
    width = _int(env, "WIDTH", 1920)
    height = _int(env, "HEIGHT", 1080)
    fps = _int(env, "FPS", 30)
    preset = (env.get("SW_PRESET") or "ultrafast").strip()

    if width % 2 or height % 2:
        raise ConfigError(f"WIDTH and HEIGHT must be even for H.264 chroma subsampling, got {width}x{height}")
    if preset not in _PRESETS:
        raise ConfigError(f"SW_PRESET must be one of {', '.join(_PRESETS)}, got {preset!r}")

    initial_mu_raw = (env.get("CHILD_INITIAL_MU") or "").strip()

    return Settings(
        start_url=(env.get("START_URL") or "about:blank").strip(),
        width=width,
        height=height,
        fps=fps,
        sw_preset=preset,
        locale=(env.get("LOCALE") or "en-US").strip(),
        timezone=(env.get("TIMEZONE") or "UTC").strip(),
        child_ready_timeout_s=_int(env, "CHILD_READY_TIMEOUT_S", 180),
        child_initial_mu=int(initial_mu_raw) if initial_mu_raw else None,
    )
