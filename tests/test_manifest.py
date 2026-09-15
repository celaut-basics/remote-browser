"""The manifest and the entrypoint, checked against each other.

This is the only kind of bug this service can still have that nothing else would
catch. `service.json` declares the environment variables a node will accept at
`nodo execute -e`; `entrypoint.sh` decides what it actually reads. Nothing joins
the two, so they drift in two directions and both are silent:

- declared and never read — the operator passes a value, the node accepts it,
  and it changes nothing. `BITRATE_KBPS` was exactly this, declared for a while
  before anyone noticed GameStream negotiates the bitrate from the client side.
- read and never declared — the entrypoint has a knob the node will refuse to
  pass, so it is stuck at its default with no way to say so.

Neither produces an error anywhere. They produce a service that quietly ignores
its own configuration, which is the same shape of failure as a parent manifest
that under-declares a network: the manifest is what somebody reads to decide what
this thing does, and it is wrong.
"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "stream", ".service", "service.json")
ENTRYPOINT = os.path.join(ROOT, "stream", "service", "entrypoint.sh")

# `NAME="${NAME:-default}"` and `NAME="${NAME}"` -- how the entrypoint takes a
# value from the environment. A bare mention in a message is not a read.
_READ = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)="\$\{\1(?::-[^}]*)?\}"', re.MULTILINE)


def _manifest():
    with open(MANIFEST) as handle:
        return json.load(handle)


def _declared():
    return set(_manifest().get("envs", []))


def _read():
    with open(ENTRYPOINT) as handle:
        return set(_READ.findall(handle.read()))


class TestEnvironment(unittest.TestCase):
    def test_everything_declared_is_read(self):
        unused = _declared() - _read()
        self.assertFalse(
            unused,
            f"declared in service.json and never read by entrypoint.sh: {sorted(unused)}. "
            "The node will accept these at `nodo execute -e` and they will change nothing.",
        )

    def test_everything_read_is_declared(self):
        undeclared = _read() - _declared()
        self.assertFalse(
            undeclared,
            f"read by entrypoint.sh and not declared in service.json: {sorted(undeclared)}. "
            "The node will refuse to pass these, so they are stuck at their defaults.",
        )


class TestSlots(unittest.TestCase):
    def test_gamestream_ports_are_all_declared(self):
        # Moonlight does not discover ports, it derives them from one base by fixed
        # offsets. A slot left out is not a missing feature, it is a session that
        # fails partway through with no useful error.
        slots = {(s["port"], s["transport"]) for s in _manifest()["api"]}
        for port in (47989, 47984, 47990, 48010):
            self.assertIn((port, "tcp"), slots, f"TCP {port} is not declared")
        for port in (47998, 47999, 48000, 48002):
            self.assertIn((port, "udp"), slots, f"UDP {port} is not declared")

    def test_no_port_is_declared_twice_on_one_transport(self):
        declared = [(s["port"], s["transport"]) for s in _manifest()["api"]]
        self.assertEqual(len(declared), len(set(declared)))

    def test_the_browser_declares_open_egress(self):
        # If this ever narrows it should be a deliberate change with a failing
        # test, not a quieter manifest nobody re-read.
        tags = [set(n.get("tags", [])) for n in _manifest().get("network", [])]
        self.assertIn({"*"}, tags)


if __name__ == "__main__":
    unittest.main()
