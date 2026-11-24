"""The stdio servers: UTF-8 whatever the locale, and they keep answering after bad input."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
