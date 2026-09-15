#!/usr/bin/env python3
"""The browser child: launching it, waiting for it, and giving it back.

``node_controller``'s own ``ServiceInterface.get_instance()`` is not used here,
and the reason is one line of that library: ``ServiceInstance`` keeps
``get_grpc_uri(instance)``, which returns the address of the *first* slot and
drops the rest. This child declares eight, because GameStream is eight -- an HTTP
port, an HTTPS port, an RTSP port, a web API, and four datagram flows -- and a
caller that knows one of them knows nothing useful. So ``launch_instance`` is
called directly and the whole ``celaut.Instance`` is kept.
"""
from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# Guarded for the same reason as in config.py: `slots()` and `offsets_survived()`
# below are the two pieces of real reasoning in this module and neither of them
# touches the node. They are testable without it; `launch` and `release` say so
# when it is missing.
try:
    from node_controller.gateway.communication import (
        generate_gateway_stub,
        launch_instance,
        stop as gateway_stop,
    )
    from node_controller.gateway.protos import celaut_pb2
    from node_controller.utils.lambdas import SHA3_256_ID
except ImportError:  # pragma: no cover - present in the image, absent under test
    generate_gateway_stub = launch_instance = gateway_stop = None
    celaut_pb2 = None
    SHA3_256_ID = None

SERVICES_DIR = "/__services__"
METADATA_DIR = "/__metadata__"

READY_POLL_S = 0.5


class ChildLaunchError(RuntimeError):
    """The node could not give us a child. We never got to observe anything."""


class ChildNotReadyError(RuntimeError):
    """It launched and never started answering.

    Distinct from a launch failure on purpose. The node reports an instance ready
    when the guest's IP answers, which under a microVM is seconds before the
    service inside it binds a port -- nodo's own log calls it "instance registered
    before the guest could call in". A request sent into that gap is refused by a
    guest that is perfectly healthy, and reading that refusal as a dead child turns
    boot latency into a diagnosis.
    """


@dataclass
class Child:
    token: str
    instance: "celaut_pb2.Instance"

    def slots(self) -> Dict[int, Tuple[str, int]]:
        """``internal port -> (ip, port)`` for every slot the node published."""
        published: Dict[int, Tuple[str, int]] = {}
        for uri_slot in self.instance.uri_slot:
            for uri in uri_slot.uri:
                if uri.ip and uri.port:
                    published[uri_slot.internal_port] = (uri.ip, uri.port)
                    break
        return published

    def slot(self, internal_port: int) -> Optional[Tuple[str, int]]:
        return self.slots().get(internal_port)

    def offsets_survived(self) -> bool:
        """Whether the published ports are still GameStream's offset family.

        Moonlight does not learn a host's ports, it *derives* them: one base and a
        fixed set of offsets, 47989 for HTTP and base-5, base+21, base+9.. for the
        rest. Nodo publishes each declared slot on a port taken from
        ``network.FREE_PORTS_RANGE``, independently, so the offsets between them
        are whatever the allocator had free -- and a Moonlight pointed at the
        published HTTP port would then compute four wrong ports for everything
        else.

        It survives in exactly one case: when the node advertises the guest's own
        bridge address, with the internal ports unchanged. That is the case this
        service is built for, because the viewer is a sibling on the same bridge
        and reaches the child directly. When it is false, the session is still
        reachable -- one ``nodo tunnel --listen`` per slot rebuilds the family on
        the caller's side -- but not by pointing a client at what ``/session``
        reports.
        """
        return all(internal == external for internal, (_, external) in self.slots().items())


def launch(
    node_url: str,
    service_hash: str,
    environment: Dict[str, bytes],
    initial_mu: Optional[int] = None,
    max_attempts: int = 3,
) -> Child:
    if launch_instance is None:
        raise ChildLaunchError(
            "node_controller is not importable: this package was built without the "
            "client library, so there is no way to ask the node for a child"
        )
    stub = generate_gateway_stub(node_url)
    config = celaut_pb2.Configuration(environment_variables=environment)
    if initial_mu is not None:
        config.initial_mu.CopyFrom(celaut_pb2.Amount(n=str(initial_mu)))

    try:
        result = launch_instance(
            gateway_stub=stub,
            hashes=[celaut_pb2.Metadata.HashTag.Hash(
                type=SHA3_256_ID, value=bytes.fromhex(service_hash),
            )],
            config=config,
            service_hash=service_hash,
            static_service_directory=SERVICES_DIR,
            static_metadata_directory=METADATA_DIR,
            dynamic_service_directory=SERVICES_DIR,
            dynamic_metadata_directory=METADATA_DIR,
            dynamic=False,
            dev_client=None,
            max_attempts=max_attempts,
            debug=lambda s: logging.debug("node_controller: %s", s),
        )
    except Exception as exc:
        raise ChildLaunchError(f"StartService failed for {service_hash[:16]}: {exc}") from exc

    child = Child(token=result.token, instance=result.instance)
    logging.info("browser child launched: token=%s slots=%s", child.token, child.slots())
    return child


def wait_until_ready(address: Tuple[str, int], timeout_s: int) -> None:
    """Block until the child accepts a TCP connection on ``address``.

    A bare connect is the right test: the port opens exactly when the service binds
    it, which is the event the node's readiness signal misses, and it costs the
    child no work, so it cannot perturb what happens next.
    """
    host, port = address
    deadline = time.monotonic() + timeout_s
    last = "never attempted"
    while True:
        try:
            with socket.create_connection((host, port), timeout=3):
                logging.info("browser child is accepting connections on %s:%s", host, port)
                return
        except OSError as exc:
            last = f"{type(exc).__name__}: {exc}"
            if time.monotonic() >= deadline:
                raise ChildNotReadyError(
                    f"{host}:{port} did not accept a connection within {timeout_s}s (last: {last})"
                )
            time.sleep(READY_POLL_S)


def release(node_url: str, child: Optional[Child]) -> None:
    """Stop the child.

    node_controller's contract is that a taken instance is returned or stopped; a
    leaked one, in its own words, remains "as zombies on the network until the
    service is removed". It also keeps drawing MU from this instance's balance,
    and this instance's balance is what pays for the session.
    """
    if child is None or gateway_stop is None:
        return
    try:
        gateway_stop(
            gateway_stub=generate_gateway_stub(node_url),
            token=child.token,
            debug=lambda s: logging.debug("node_controller: %s", s),
        )
        logging.info("browser child %s stopped", child.token)
    except Exception as exc:
        logging.warning("could not stop browser child %s: %s", child.token, exc)
