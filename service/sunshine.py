#!/usr/bin/env python3
"""The child's Sunshine API, from the parent.

This is the whole reason the administrator credentials are generated up here and
pushed down: Sunshine's pairing step needs them, and the alternative is a human
opening Sunshine's own web UI on the child. That would mean publishing port 47990
to whoever is driving the session and handing them an administrator password for
a machine they do not own -- one that can rewrite the encoder, the capture method
and the application list. Pairing needs a four-digit PIN and nothing else, so the
parent takes the PIN and keeps the password.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import requests
import urllib3

# The child generates a self-signed certificate at first boot: there is no name to
# issue one for (the address comes from the node's port allocator) and no authority
# either side would agree on. Verification is therefore off, and this is the one
# place it is -- the credentials below are what authenticates the call, the leg is
# parent-to-child over a bridge inside one host, and pretending to verify a
# certificate nobody signed would be worse than saying so here.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TIMEOUT_S = 10


class SunshineError(RuntimeError):
    pass


class Sunshine:
    def __init__(self, address: Tuple[str, int], user: str, password: str):
        host, port = address
        self.base = f"https://{host}:{port}"
        self.auth = (user, password)

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = requests.post(
                f"{self.base}{path}", json=payload, auth=self.auth,
                verify=False, timeout=TIMEOUT_S,
            )
        except requests.RequestException as exc:
            raise SunshineError(f"POST {path} did not reach the child: {exc}") from exc
        if response.status_code == 401:
            raise SunshineError(
                f"POST {path} was rejected: the child did not accept the credentials this "
                "instance generated for it, so the two are not from the same session"
            )
        if not response.ok:
            raise SunshineError(f"POST {path} returned {response.status_code}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError:
            return {}

    def reachable(self) -> bool:
        try:
            requests.get(f"{self.base}/", auth=self.auth, verify=False, timeout=TIMEOUT_S)
            return True
        except requests.RequestException:
            return False

    def apply_pin(self, pin: str, name: str, pairing_id: Optional[str] = None) -> dict:
        """Complete a pairing a client has already started.

        The order matters and is not the intuitive one: Moonlight generates the PIN
        and shows it, then waits; the host is what enters it. So this call only does
        anything while a client is mid-handshake, and calling it first returns a
        refusal rather than arming anything.

        ``pairing_id`` selects among several pending requests. It is optional
        because a version of Sunshine that predates explicit selection takes the PIN
        alone, and because a session with one client -- the shape this service is
        built for -- has exactly one request to apply it to.
        """
        if not (pin.isdigit() and len(pin) == 4):
            raise SunshineError(f"a GameStream PIN is four digits, got {pin!r}")
        payload = {"pin": pin, "name": name}
        if pairing_id:
            payload["pairing_id"] = pairing_id
        result = self._post("/api/pin", payload)
        logging.info("applied pairing PIN for client %r: %s", name, result)
        return result
