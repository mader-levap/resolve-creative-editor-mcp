"""The stdio servers: UTF-8 whatever the locale, and they keep answering after bad input."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests.support import ROOT  # also gives the servers a temporary bridge folder

from resolve_editor.servers import child

TEXT = "Zażółć Łódź 日本語"  # Ł is C5 81 in UTF-8, and 0x81 is undefined in cp1252: no lossless mis-decoding


def cp1252_env() -> dict[str, str]:
    """A process whose stdio would be cp1252 unless the server sets UTF-8 itself (PYTHONUTF8 not set)."""
    env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0", RESOLVE_MCP_REPO=tempfile.mkdtemp(),
               RESOLVE_MCP_SERVER="missing.py", RESOLVE_MCP_PYTHON="missing.exe")
    env.pop("RESOLVE_MCP_COMMAND", None)
    return env


class StdioServer(unittest.TestCase):
    def start(self, script: str) -> subprocess.Popen:
        p = subprocess.Popen([sys.executable, str(ROOT / script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, encoding="utf-8", env=cp1252_env())
        self.addCleanup(self.stop, p)
        return p

    def stop(self, p):
        assert p.stdin is not None and p.stdout is not None
        p.stdin.close()  # end of input: the server stops by itself
        p.wait(10)
        p.stdout.close()

    def send(self, p, *lines):
        p.stdin.write("".join(line + "\n" for line in lines))
        p.stdin.flush()

    def reply(self, p):
        line = p.stdout.readline()
        self.assertTrue(line, "the server stopped")
        return json.loads(line)

    def rpc(self, i, method, params=None):
        return json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}, ensure_ascii=False)

    def test_gateway_answers_in_utf8(self):
        p = self.start("unified_server.py")
        # a ping after it: if the first reply can't be written, the next line is the ping's, not a hang
        self.send(p, self.rpc(1, "tools/call", {"name": TEXT, "arguments": {}}), self.rpc(2, "ping"))
        r = self.reply(p)
        self.assertEqual(r["id"], 1)
        self.assertIn(TEXT, r["result"]["content"][0]["text"])

    def test_legacy_reads_utf8(self):
        p = self.start("mcp_server.py")
        self.send(p, self.rpc(1, "tools/call", {"name": TEXT, "arguments": {}}))
        self.assertIn(TEXT, self.reply(p)["result"]["content"][0]["text"])

    def test_legacy_keeps_answering_after_bad_input(self):
        p = self.start("mcp_server.py")
        self.send(p, "not json", self.rpc(1, "ping"))
        self.assertEqual(self.reply(p), {"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700, "message": "parse error"}})
        self.assertEqual(self.reply(p)["id"], 1)


class ChildClose(unittest.TestCase):
    def test_close_stops_the_process_and_its_pipes(self):
        c = child.Child("fake", [sys.executable, str(ROOT / "tests" / "fake_mcp.py")], ROOT)
        c.start("2025-03-26")
        proc = c.proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None
        c.close()
        self.assertIsNotNone(proc.returncode)
        self.assertTrue(proc.stdin.closed and proc.stdout.closed)
        c.close()  # twice is harmless

    def test_close_lets_the_process_exit_by_itself(self):
        # it gets to its own exit (atexit handlers, coverage data); terminate() is only the fallback
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        marker = os.path.join(folder.name, "exited")
        with mock.patch.dict(os.environ, FAKE_MCP_EXIT_FILE=marker):
            c = child.Child("fake", [sys.executable, str(ROOT / "tests" / "fake_mcp.py")], ROOT)
            c.start("2025-03-26")
        c.close()
        self.assertTrue(os.path.exists(marker))

    def test_a_child_that_ignores_the_end_of_its_input_is_terminated(self):
        c = start_child(self, FAKE_MCP_IGNORE_EOF="1")
        proc = c.proc
        assert proc is not None
        began = time.monotonic()
        c.close()
        self.assertIsNotNone(proc.returncode)
        self.assertLess(time.monotonic() - began, 6, "2 s grace, then terminate")


def start_child(test, *tools, **env):
    """A started Child running tests/fake_mcp.py with these tools and FAKE_MCP_* switches; closed after the test."""
    with mock.patch.dict(os.environ, env):
        c = child.Child("fake", [sys.executable, str(ROOT / "tests" / "fake_mcp.py"), *tools], ROOT)
        c.start("2025-03-26")
    test.addCleanup(c.close)
    return c


class ChildRequests(unittest.TestCase):
    def test_a_request_that_times_out_raises_and_its_late_reply_is_discarded(self):
        c = start_child(self, "slow", "hello", FAKE_MCP_SLOW="1")
        with self.assertRaises(TimeoutError):
            c.request("tools/call", {"name": "slow", "arguments": {}}, timeout=0.2)
        # the slow reply arrives first; the next request must skip it and get its own
        r = c.request("tools/call", {"name": "hello", "arguments": {}}, timeout=10)
        self.assertEqual(r["result"]["content"][0]["text"], "called:hello")

    def test_a_child_that_exits_mid_call_fails_the_call_at_once(self):  # docs/ISSUES.md C-07
        c = start_child(self, "exit")
        began = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "fake exited while handling tools/call"):
            c.request("tools/call", {"name": "exit", "arguments": {}}, timeout=20)
        self.assertLess(time.monotonic() - began, 5, "not after the timeout")
        with self.assertRaisesRegex(RuntimeError, "not running"):  # and later calls fail at once too
            c.request("tools/call", {"name": "exit", "arguments": {}}, timeout=20)

    def test_lines_that_are_not_replies_are_skipped(self):
        c = start_child(self, FAKE_MCP_NOISE="1")
        r = c.request("tools/call", {"name": "hello", "arguments": {}}, timeout=10)
        self.assertEqual(r["result"]["content"][0]["text"], "called:hello")

    def test_a_failed_handshake_raises(self):
        c = child.Child("fake", [sys.executable, str(ROOT / "tests" / "fake_mcp.py")], ROOT)
        self.addCleanup(c.close)
        with mock.patch.dict(os.environ, FAKE_MCP_INIT_ERROR="1"), \
                self.assertRaisesRegex(RuntimeError, "fake initialize failed: .*cannot start"):
            c.start("2025-03-26")

    def test_a_request_before_start_raises(self):
        c = child.Child("fake", [sys.executable, "-c", ""], ROOT)
        with self.assertRaisesRegex(RuntimeError, "fake MCP process is not running"):
            c.request("ping", {})
        c.close()  # nothing started: harmless


if __name__ == "__main__":
    unittest.main()
