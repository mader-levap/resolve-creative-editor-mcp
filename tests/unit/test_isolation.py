"""No test file may use the user's bridge folder, also when it runs alone (docs/ISSUES.md I-14)."""
import os
import subprocess
import sys
import tempfile
import unittest

from tests.support import ROOT

PROBE = """import importlib, os, sys
importlib.import_module("tests.unit." + sys.argv[1])
from resolve_editor import paths
print(paths.DIR)
print(os.environ.get("RESOLVE_BRIDGE_DIR"))"""


class Isolation(unittest.TestCase):
    def test_every_test_file_alone_uses_a_temporary_bridge_folder(self):
        with tempfile.TemporaryDirectory() as home:
            users = os.path.join(home, "resolve-claude-bridge")  # stands in for the user's bridge folder
            env = dict(os.environ, RESOLVE_BRIDGE_DIR=users, PYTHONDONTWRITEBYTECODE="1")
            names = sorted(p.stem for p in (ROOT / "tests" / "unit").glob("test_*.py"))
            self.assertGreater(len(names), 10)  # finding none would pass without checking anything
            for name in names:
                with self.subTest(test_file=name):
                    p = subprocess.run([sys.executable, "-c", PROBE, name], cwd=ROOT, env=env, capture_output=True,
                                       text=True, timeout=60)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    used_here, given_to_children = p.stdout.splitlines()[-2:]
                    self.assertNotEqual(used_here, users)
                    self.assertNotEqual(given_to_children, users)
