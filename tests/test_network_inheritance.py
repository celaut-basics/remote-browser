"""The parent's network declaration is the ceiling for everything it launches.

This test exists because the rule it checks was got wrong once, in this
repository, and nothing caught it. `filter_networks_with_ancestors` intersects a
child's requested networks with its father's spec, by tag, and then with its
father's father, up the chain. A parent that declares less than its child does not
produce an error: the filter returns an empty list, `build_network_resolution`
raises nothing, and the guest boots with the default `block_all` and no allow
rules. The service starts, looks healthy, and reaches nothing.

So the rule is asserted here against the two manifests themselves, because the
place it will be broken again is an edit to one of them, and the place it will be
noticed otherwise is a browser that mysteriously loads no page.
"""
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.join(ROOT, ".service", "service.json")
CHILD = os.path.join(ROOT, "browser", ".service", "service.json")


def _networks(path):
    with open(path) as handle:
        return json.load(handle).get("network", [])


def _tags(networks):
    return [set(entry.get("tags", [])) for entry in networks]


class TestNetworkInheritance(unittest.TestCase):
    def test_every_child_network_tag_matches_one_of_the_parents(self):
        parent, child = _tags(_networks(PARENT)), _tags(_networks(CHILD))
        for requested in child:
            # match_networks() in src/manager/networks.py: at least one shared tag.
            # Not a subset test, and not a glob -- `*` is matched literally, so a
            # parent declaring ["ipv4", "public"] authorizes a child asking for
            # ["*"] exactly as little as a parent declaring nothing.
            self.assertTrue(
                any(requested & granted for granted in parent),
                f"the child asks for {sorted(requested)} and no network in the parent "
                f"shares a tag with it ({[sorted(g) for g in parent]}). The child would "
                "launch with no egress at all, and the launch would report success.",
            )

    def test_the_parent_declares_something_if_the_child_does(self):
        if _networks(CHILD) and not _networks(PARENT):
            self.fail(
                "the child declares a network and the parent declares none: an empty "
                "parent grant is an empty child grant, whatever the child asked for"
            )

    def test_the_child_is_the_one_that_needs_the_web(self):
        # Belt and braces on the thing this service is actually about: if the
        # browser ever stops declaring open egress, that is a deliberate change and
        # should show up as a failing test rather than as a quieter manifest.
        self.assertIn({"*"}, _tags(_networks(CHILD)))


if __name__ == "__main__":
    unittest.main()
