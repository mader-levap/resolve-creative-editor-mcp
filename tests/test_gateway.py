"""The gateway, run as a process."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests.support import ROOT  # also gives the gateway a temporary bridge folder


class GatewayTests(unittest.TestCase):
    def test_namespaced_routing(self):
        env=os.environ.copy()
        fake=[sys.executable,str(ROOT/"tests"/"fake_mcp.py")]
        env["RESOLVE_MCP_COMMAND"]=json.dumps(fake)
        env["LEGACY_MCP_COMMAND"]=json.dumps(fake)
        proc=subprocess.Popen([sys.executable,str(ROOT/"unified_server.py")],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding="utf-8",env=env)
        def request(i,method,params=None):
            proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":i,"method":method,"params":params or {}})+"\n")
            proc.stdin.flush()
            while True:
                line=proc.stdout.readline()
                if not line:
                    raise AssertionError("gateway closed")
                data=json.loads(line)
                if data.get("id")==i:
                    return data
        try:
            init=request(1,"initialize",{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1"}})
            self.assertEqual(init["result"]["serverInfo"]["name"],"resolve-creative-editor")
            proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})+"\n")
            proc.stdin.flush()
            tools=request(3,"tools/list")["result"]["tools"]
            names={x["name"] for x in tools}
            self.assertIn("resolve__hello",names)
            self.assertIn("legacy__hello",names)
            self.assertIn("media__probe_media",names)
            result=request(4,"tools/call",{"name":"resolve__hello","arguments":{}})
            self.assertEqual(result["result"]["content"][0]["text"],"called:hello")
            result=request(5,"tools/call",{"name":"legacy__hello","arguments":{}})
            self.assertEqual(result["result"]["content"][0]["text"],"called:hello")
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream:
                    stream.close()


class GatewayResilience(unittest.TestCase):
    def rpc(self, env):
        p = subprocess.Popen([sys.executable, str(ROOT / "unified_server.py")], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env)
        self.addCleanup(lambda: (p.terminate(), p.wait(5), p.stdin.close(), p.stdout.close()))

        def call(i, m, params=None):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": m, "params": params or {}}) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline())
        return call

    def test_runs_without_upstream_and_guards(self):
        env = dict(os.environ, RESOLVE_MCP_REPO=tempfile.mkdtemp(), RESOLVE_MCP_SERVER="missing.py",
                   RESOLVE_MCP_PYTHON="missing.exe")
        env.pop("RESOLVE_MCP_COMMAND", None)
        call = self.rpc(env)
        self.assertIn("instructions", call(1, "initialize", {"protocolVersion": "2025-03-26"})["result"])
        tools = call(2, "tools/list")["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertTrue({"edit__move_item", "edit__timeline_summary", "legacy__get_state"} <= names)
        self.assertFalse([n for n in names if n.startswith("resolve__")])
        self.assertLess(len(json.dumps(tools)), 60000, "tool list stays small enough for context")
        r = call(3, "tools/call", {"name": "legacy__start_render", "arguments": {}})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("confirm", r["content"][0]["text"])
