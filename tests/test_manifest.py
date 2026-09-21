"""Each service's manifest, checked against its own entrypoint.

Three services, one shape. The class of bug this catches is the one nothing else
would: `service.json` declares what a node will accept and which ports it will
open, `entrypoint.sh` decides what is actually read and bound, and nothing joins
the two. They drift in both directions and both are silent.

- Declared and never read — the operator passes a value at `nodo execute -e`, the
  node accepts it, and it changes nothing. `BITRATE_KBPS` was exactly this,
  declared for a while before anyone noticed GameStream negotiates the bitrate
  from the client side.
- Read and never declared — the entrypoint has a knob the node will refuse to
  pass, so it is stuck at its default with no way to say otherwise.
- A slot declared on a port nothing binds — the node opens a firewall hole and
  publishes an address where nobody answers.

None of the three produces an error anywhere. They produce a service that quietly
ignores its own manifest, which is the same shape of failure as a parent that
under-declares a network: the manifest is what somebody reads to decide what this
thing does, and it is wrong.
"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICES = ("stream", "waypipe", "vnc")

# `NAME="${NAME:-default}"` or `NAME="${NAME}"` -- how an entrypoint takes a value
# from the environment. A mention inside a message is not a read.
_READ = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)="\$\{\1(?::-[^}]*)?\}"', re.MULTILINE)


def manifest(service):
    with open(os.path.join(ROOT, service, ".service", "service.json")) as handle:
        return json.load(handle)


def entrypoint(service):
    with open(os.path.join(ROOT, service, "service", "entrypoint.sh")) as handle:
        return handle.read()


def dockerfile(service):
    with open(os.path.join(ROOT, service, ".service", "Dockerfile")) as handle:
        return handle.read()


# `COPY <origin> <dest>`, skipping flags like --from=builder.
_COPY = re.compile(r"^\s*COPY\s+((?:--[^\s]+\s+)*)([^\s]+)\s+([^\s]+)\s*$", re.MULTILINE | re.IGNORECASE)


class TestLayout(unittest.TestCase):
    def test_each_service_is_complete(self):
        for service in SERVICES:
            for relative in (".service/service.json", ".service/pack_config.json",
                             ".service/Dockerfile", "service/entrypoint.sh",
                             "NODE-REQUIREMENTS.md"):
                path = os.path.join(ROOT, service, relative)
                self.assertTrue(os.path.isfile(path), f"{service}: missing {relative}")

    def test_entry_path_points_at_the_file_that_exists(self):
        for service in SERVICES:
            entry = manifest(service)["init"]["entry_path"]
            self.assertTrue(
                os.path.isfile(os.path.join(ROOT, service, *entry)),
                f"{service}: init.entry_path {entry} is not a file in the tree. It packs "
                "fine and the instance can never start.",
            )


class TestPackerContext(unittest.TestCase):
    """The one difference between `docker build` here and `nodo pack` there.

    The packer builds with the context set to `.service/`, stages the project
    under `service/` inside it, and rewrites COPY origins that start with `.` to
    match. A bare relative origin is NOT rewritten -- PACKING.md is explicit --
    so `COPY service /service` resolves to `.service/service` under the packer
    and to `<svc>/service` under docker, and only one of those is the tree.

    It cost a pack: the build ran the whole apt layer and then died on
    `chmod: cannot access '/service/entrypoint.sh'`. Nothing in the repository
    could have caught it, because a plain `docker build` is happy either way.
    """

    def test_relative_copy_origins_are_dot_prefixed(self):
        for service in SERVICES:
            for flags, origin, _dest in _COPY.findall(dockerfile(service)):
                if "--from=" in flags or origin.startswith("/") or "://" in origin:
                    continue
                self.assertTrue(
                    origin.startswith("./"),
                    f"{service}: `COPY {origin}` is a bare relative origin. The packer "
                    "rewrites only origins beginning with '.', so this reads "
                    f"`.service/{origin}` under `nodo pack` and fails there while "
                    "building fine under `docker build`. Write `./" + origin + "`.",
                )

    def test_the_entry_path_is_where_the_dockerfile_puts_it(self):
        # entry_path is absolute in the packed filesystem. The COPY destination is
        # what decides where that file lands, and the two are written in different
        # files by different hands.
        for service in SERVICES:
            entry = "/" + "/".join(manifest(service)["init"]["entry_path"])
            dests = [dest.rstrip("/") for _f, _o, dest in _COPY.findall(dockerfile(service))]
            self.assertTrue(
                any(entry == dest or entry.startswith(dest + "/") for dest in dests),
                f"{service}: init.entry_path is {entry}, and no COPY in the Dockerfile "
                f"puts anything there (destinations: {dests}). The service packs and "
                "the instance cannot start.",
            )


class TestEnvironment(unittest.TestCase):
    def test_everything_declared_is_read(self):
        for service in SERVICES:
            unused = set(manifest(service).get("envs", [])) - set(_READ.findall(entrypoint(service)))
            self.assertFalse(
                unused,
                f"{service}: declared in service.json and never read by entrypoint.sh: "
                f"{sorted(unused)}. The node will accept these at `nodo execute -e` and "
                "they will change nothing.",
            )

    def test_everything_read_is_declared(self):
        for service in SERVICES:
            undeclared = set(_READ.findall(entrypoint(service))) - set(manifest(service).get("envs", []))
            self.assertFalse(
                undeclared,
                f"{service}: read by entrypoint.sh and not declared in service.json: "
                f"{sorted(undeclared)}. The node will refuse to pass these, so they are "
                "stuck at their defaults.",
            )


class TestSlots(unittest.TestCase):
    def test_a_single_slot_port_appears_in_its_entrypoint(self):
        # Not proof that it is bound, but it catches the drift that matters: a
        # port changed on one side and not the other. A slot nothing binds is a
        # firewall hole and a published address where nobody answers.
        for service in ("waypipe", "vnc"):
            for slot in manifest(service)["api"]:
                self.assertIn(
                    str(slot["port"]), entrypoint(service),
                    f"{service}: slot {slot['port']} is declared and the number appears "
                    "nowhere in entrypoint.sh",
                )

    def test_no_port_is_declared_twice_on_one_transport(self):
        for service in SERVICES:
            declared = [(s["port"], s["transport"]) for s in manifest(service)["api"]]
            self.assertEqual(len(declared), len(set(declared)), f"{service}: duplicate slot")

    def test_the_gamestream_family_matches_the_base_in_the_entrypoint(self):
        # stream/ is the exception to the test above, and for the reason the whole
        # architecture turns on: Moonlight does not discover ports, it DERIVES them
        # from one base by fixed offsets. Only the base is written down -- as
        # `port =` in the sunshine.conf the entrypoint generates -- and the other
        # seven exist only because the manifest declares them at the right
        # distance from it. Move the base without moving the manifest and a session
        # fails partway through with no useful error, which is what this asserts
        # against.
        found = re.search(r"^port = (\d+)$", entrypoint("stream"), re.MULTILINE)
        self.assertIsNotNone(found, "stream: no `port =` base in the generated sunshine.conf")
        base = int(found.group(1))
        slots = {(s["port"], s["transport"]) for s in manifest("stream")["api"]}
        for offset, what in ((0, "HTTP"), (-5, "HTTPS"), (1, "web API"), (21, "RTSP")):
            self.assertIn((base + offset, "tcp"), slots,
                          f"base{offset:+d} ({base + offset}/tcp, {what}) is not declared")
        for offset, what in ((9, "video"), (10, "control"), (11, "audio"), (13, "mic")):
            self.assertIn((base + offset, "udp"), slots,
                          f"base{offset:+d} ({base + offset}/udp, {what}) is not declared")

    def test_the_single_slot_services_say_what_they_speak(self):
        # nodo display is proposed to find its slot by protocol_stack rather than
        # by a port number the user has to be told; a VNC viewer and a tunnel are
        # chosen the same way by whoever reads the manifest.
        for service, protocol in (("waypipe", "waypipe"), ("vnc", "rfb")):
            slots = manifest(service)["api"]
            self.assertEqual(len(slots), 1, f"{service}: expected exactly one slot")
            self.assertIn(protocol, slots[0]["protocol"])
            self.assertEqual(slots[0]["transport"], "tcp")


class TestNetwork(unittest.TestCase):
    def test_all_three_declare_open_egress(self):
        # If this ever narrows it should be a deliberate change with a failing
        # test, not a quieter manifest nobody re-read.
        for service in SERVICES:
            tags = [set(n.get("tags", [])) for n in manifest(service).get("network", [])]
            self.assertIn({"*"}, tags, f"{service}: no open-egress network declared")


if __name__ == "__main__":
    unittest.main()
