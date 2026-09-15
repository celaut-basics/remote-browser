"""Whether GameStream's port offsets survived this node's port allocator.

Moonlight derives every port from one base by fixed offsets, and nodo assigns each
declared slot a host port out of its free range independently. So the question
`offsets_survived` answers is the difference between a session a client can open
and one that fails looking like a network fault -- which makes it worth asserting
against both shapes rather than trusting it to be obvious.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service"))

import child  # noqa: E402


class _Uri:
    def __init__(self, ip, port):
        self.ip, self.port = ip, port


class _UriSlot:
    def __init__(self, internal_port, uris):
        self.internal_port, self.uri = internal_port, uris


class _Instance:
    def __init__(self, uri_slots):
        self.uri_slot = uri_slots


def _child(mapping, ip="10.0.0.7"):
    return child.Child(
        token="t",
        instance=_Instance([_UriSlot(i, [_Uri(ip, e)]) for i, e in mapping.items()]),
    )


class TestSlots(unittest.TestCase):
    def test_guest_address_keeps_the_family(self):
        c = _child({47989: 47989, 47984: 47984, 48010: 48010, 47998: 47998})
        self.assertTrue(c.offsets_survived())
        self.assertEqual(c.slot(47989), ("10.0.0.7", 47989))

    def test_remapped_ports_break_the_family(self):
        # What the node does by default: each slot gets whatever was free, so the
        # distance between the HTTP port and the video port is no longer +9.
        c = _child({47989: 13001, 47984: 13007, 48010: 13002, 47998: 13040})
        self.assertFalse(c.offsets_survived())

    def test_a_slot_the_node_could_not_advertise_is_absent_not_wrong(self):
        # local_execution appends a Uri_Slot with no uri when it has no address to
        # advertise. Reporting that as an address would send a client nowhere.
        c = child.Child(token="t", instance=_Instance([_UriSlot(47989, [])]))
        self.assertIsNone(c.slot(47989))
        self.assertEqual(c.slots(), {})


if __name__ == "__main__":
    unittest.main()
