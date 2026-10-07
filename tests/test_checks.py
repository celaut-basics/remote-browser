"""The launcher-value checks in `service/checks.sh`, run in bash.

Each entrypoint reads `/service/checks.sh` before it uses a value from
`nodo execute -e`. These tests run the same functions with a `fail` that prints
and exits, so they need bash and nothing else. They do not need root, Docker or
a node.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICES = ("stream", "waypipe", "vnc")
CHECKS = os.path.join(ROOT, "vnc", "service", "checks.sh")

DEFAULTS = {
    "WIDTH": "1920",
    "HEIGHT": "1080",
    "START_URL": "about:blank",
    "LOCALE": "en-US",
    "TIMEZONE": "UTC",
}


def run(script, **env):
    """Run `script` in bash after checks.sh. Return (exit code, output)."""
    prelude = 'fail() { printf "FATAL: %s\\n" "$*"; exit 1; }\n. "$CHECKS"\n'
    full_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "CHECKS": CHECKS}
    full_env.update(env)
    done = subprocess.run(["bash", "-c", prelude + script], env=full_env,
                          capture_output=True, text=True, timeout=20)
    return done.returncode, done.stdout + done.stderr


class TestCopies(unittest.TestCase):
    def test_the_three_copies_are_equal(self):
        # Each service packs only its own directory, so the file is copied.
        # A fix in one copy that does not get to the others is a silent drift.
        with open(CHECKS, "rb") as handle:
            reference = handle.read()
        for service in SERVICES:
            with open(os.path.join(ROOT, service, "service", "checks.sh"), "rb") as handle:
                self.assertEqual(handle.read(), reference,
                                 f"{service}/service/checks.sh differs from vnc/service/checks.sh")

    def test_each_entrypoint_reads_it_where_the_image_puts_it(self):
        for service in SERVICES:
            with open(os.path.join(ROOT, service, "service", "entrypoint.sh")) as handle:
                self.assertIn("\n. /service/checks.sh\n", handle.read(),
                              f"{service}: entrypoint.sh does not read /service/checks.sh")


class TestBrowserValues(unittest.TestCase):
    def check(self, **overrides):
        env = dict(DEFAULTS, **overrides)
        return run("check_browser_values", **env)

    def test_the_defaults_pass(self):
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_good_values_pass(self):
        for overrides in ({"WIDTH": "1280", "HEIGHT": "800"},
                          {"START_URL": "https://example.com/a?b=-c"},
                          {"LOCALE": "pt_BR"}, {"LOCALE": "zh-Hant-TW"},
                          {"TIMEZONE": "Europe/Madrid"}):
            code, out = self.check(**overrides)
            self.assertEqual(code, 0, f"{overrides}: {out}")

    def test_bad_values_stop_the_instance(self):
        for overrides in ({"WIDTH": "abc"}, {"WIDTH": "0800"}, {"WIDTH": "100"},
                          {"WIDTH": "99999"}, {"HEIGHT": ""}, {"HEIGHT": "1080 "},
                          {"START_URL": "--remote-debugging-port=9222"},
                          {"START_URL": "-x"},
                          {"LOCALE": "en-US;id"}, {"LOCALE": "e"},
                          {"TIMEZONE": "../../etc/passwd"}, {"TIMEZONE": "Not/AZone"},
                          {"TIMEZONE": "UTC\nX=1"}):
            code, out = self.check(**overrides)
            self.assertEqual(code, 1, f"{overrides!r} passed: {out}")
            self.assertIn("FATAL:", out)

    def test_one_of(self):
        self.assertEqual(run("need_one_of P medium ultrafast medium")[0], 0)
        code, out = run('need_one_of P "medium\nx = y" ultrafast medium')
        self.assertEqual(code, 1, out)

    def test_timezone_uses_the_zoneinfo_directory(self):
        # The happy path above uses the host zoneinfo. A guest without tzdata
        # would still pass that test. Point ZONEINFO at an empty dir so UTC
        # must exist as a file in the image, not on this Mac.
        with tempfile.TemporaryDirectory() as zoneinfo:
            code, out = self.check(TIMEZONE="UTC", ZONEINFO=zoneinfo)
            self.assertEqual(code, 1, out)
            self.assertIn("FATAL:", out)
            with open(os.path.join(zoneinfo, "UTC"), "wb"):
                pass
            code, out = self.check(TIMEZONE="UTC", ZONEINFO=zoneinfo)
            self.assertEqual(code, 0, out)


class TestDns(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.file = os.path.join(self.dir, "resolv.conf")

    def tearDown(self):
        shutil.rmtree(self.dir)

    def set_dns(self, servers, existing=None):
        if existing is not None:
            with open(self.file, "w") as handle:
                handle.write(existing)
        code, out = run('set_dns "$SERVERS" "$FILE"', SERVERS=servers, FILE=self.file)
        content = None
        if os.path.exists(self.file):
            with open(self.file) as handle:
                content = handle.read()
        return code, out, content

    def test_unset_keeps_the_file_of_the_image(self):
        image = "# image\nnameserver 1.1.1.1\nnameserver 1.0.0.1\n"
        code, out, content = self.set_dns("", existing=image)
        self.assertEqual((code, content), (0, image), out)

    def test_unset_and_no_nameserver_gives_a_fallback(self):
        for existing in (None, ""):
            code, out, content = self.set_dns("", existing=existing)
            self.assertEqual(code, 0, out)
            self.assertEqual(content, "nameserver 1.1.1.1\nnameserver 1.0.0.1\n")

    def test_a_list_replaces_the_file(self):
        code, out, content = self.set_dns("9.9.9.9, 149.112.112.112",
                                          existing="nameserver 1.1.1.1\n")
        self.assertEqual(code, 0, out)
        self.assertEqual(content, "nameserver 9.9.9.9\nnameserver 149.112.112.112\n")

    def test_bad_lists_stop_and_keep_the_file(self):
        image = "nameserver 1.1.1.1\n"
        for servers in ("1.2.3", "256.1.1.1", "9.9.9.9,a.b.c.d", " , ",
                        "1.1.1.1 2.2.2.2 3.3.3.3 4.4.4.4", "1.1.1.1;reboot"):
            code, out, content = self.set_dns(servers, existing=image)
            self.assertEqual(code, 1, f"{servers!r} passed: {out}")
            self.assertEqual(content, image, f"{servers!r} changed the file")


class TestNodeAddress(unittest.TestCase):
    ROUTE = (
        "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
        "eth0\t00000000\t01C8A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
        "eth0\t00C8A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
    )

    def address(self, table):
        with tempfile.NamedTemporaryFile("w", suffix=".route", delete=False) as handle:
            handle.write(table)
        try:
            return run('node_address "$ROUTE"', ROUTE=handle.name)
        finally:
            os.unlink(handle.name)

    def test_the_default_gateway_of_the_nodo_bridge(self):
        # 192.168.200.1 is nodo's default NETWORK_GATEWAY_IP.
        code, out = self.address(self.ROUTE)
        self.assertEqual((code, out.strip()), (0, "192.168.200.1"))

    def test_no_default_route_is_an_error(self):
        code, _out = self.address(self.ROUTE.splitlines(True)[0] + self.ROUTE.splitlines(True)[2])
        self.assertEqual(code, 1)


@unittest.skipUnless(shutil.which("shellcheck"), "shellcheck is not installed")
class TestShellcheck(unittest.TestCase):
    def test_the_entrypoints_are_clean(self):
        for service in SERVICES:
            directory = os.path.join(ROOT, service, "service")
            done = subprocess.run(["shellcheck", "-x", "entrypoint.sh", "checks.sh"],
                                  cwd=directory, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, f"{service}:\n{done.stdout}{done.stderr}")


if __name__ == "__main__":
    unittest.main()
