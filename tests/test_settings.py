"""The settings logic, exercised without the node's client library.

`config.resolve` is the only place this service turns a string somebody typed into
a number the child is launched with, and two of its checks are the kind that only
show up as a corrupt stream three layers away: an odd width, and a preset x264 has
never heard of. Both are cheap to assert here and expensive to discover there.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service"))

import config  # noqa: E402


class TestResolve(unittest.TestCase):
    def test_defaults(self):
        s = config.resolve({})
        self.assertEqual((s.width, s.height, s.fps), (1920, 1080, 30))
        self.assertEqual(s.sw_preset, "ultrafast")
        self.assertEqual(s.start_url, "about:blank")
        self.assertIsNone(s.child_initial_mu)

    def test_odd_resolution_is_refused(self):
        # H.264 4:2:0 subsamples chroma by two in each direction, so an odd
        # dimension is not a smaller picture, it is one the decoder reads wrong.
        with self.assertRaises(config.ConfigError):
            config.resolve({"WIDTH": "1921"})
        with self.assertRaises(config.ConfigError):
            config.resolve({"HEIGHT": "1081"})

    def test_unknown_preset_is_refused(self):
        with self.assertRaises(config.ConfigError):
            config.resolve({"SW_PRESET": "fastest"})

    def test_non_numeric_is_refused_by_name(self):
        with self.assertRaises(config.ConfigError) as ctx:
            config.resolve({"FPS": "sixty"})
        self.assertIn("FPS", str(ctx.exception))

    def test_child_environment_carries_the_credentials_and_not_the_defaults(self):
        env = config.resolve({"START_URL": "https://example.org", "WIDTH": "1280", "HEIGHT": "720"})
        child_env = env.child_environment("nodo", "hunter2")
        self.assertEqual(child_env["ADMIN_PASS"], b"hunter2")
        self.assertEqual(child_env["WIDTH"], b"1280")
        # Everything the child reads must be here: an env var the parent forgets is
        # an env var the child silently defaults, and the two then disagree about
        # the resolution being encoded.
        self.assertEqual(
            set(child_env),
            {"START_URL", "WIDTH", "HEIGHT", "FPS", "SW_PRESET",
             "LOCALE", "TIMEZONE", "ADMIN_USER", "ADMIN_PASS"},
        )


class TestDependencyLookup(unittest.TestCase):
    def test_reads_the_hash_the_packer_wrote(self):
        digest = "ab" * 32
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".dependencies"), "w") as handle:
                handle.write(f"OTHER=00\nBROWSER={digest}\n")
            original = config._SEARCH_ROOTS
            config._SEARCH_ROOTS = (tmp,)
            try:
                self.assertEqual(config.find_dependency_hash("BROWSER"), digest)
            finally:
                config._SEARCH_ROOTS = original

    def test_missing_entry_names_every_path_it_tried(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = config._SEARCH_ROOTS
            config._SEARCH_ROOTS = (tmp,)
            try:
                with self.assertRaises(config.ConfigError) as ctx:
                    config.find_dependency_hash("BROWSER")
            finally:
                config._SEARCH_ROOTS = original
        self.assertIn(tmp, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
