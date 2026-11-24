"""The gateway and the legacy server in this process: routing, startup, and the JSON-RPC loops of both main()s.

Children are fakes here; tests/unit/test_gateway.py and test_stdio.py run the real processes."""
import base64
import io
import json
import os
import tempfile
import unittest
from typing import Any
from unittest import mock

from tests.support import Base, FakeResolve, sample_items

from resolve_editor import audit, dispatch, media, outcome
from resolve_editor.servers import gateway, legacy
from resolve_editor.tools import diagnostics


class FakeChild:
    """Stands in for servers.child.Child: `replies` maps a tool or method to its reply, or to an exception."""

    def __init__(self, tools=("hello",), replies=None, label="fake", fail_start=False):
        self.label, self.fail_start = label, fail_start
        self.tools = [{"name": n, "description": "fake", "inputSchema": {"type": "object", "properties": {}}}
                      for n in tools]
        self.initialize_result = {"protocolVersion": "2025-03-26", "capabilities": {"resources": {}}}
        self.replies = dict(replies or {})
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def start(self, protocol):
        if self.fail_start:
            raise RuntimeError("no such program")

    def request(self, method, params, timeout=180.0):
        self.calls.append((method, params))
        key = params.get("name") if method == "tools/call" else method
        if key == "resolve_control":
            key = "resolve_control:" + params["arguments"]["action"]
        reply = self.replies.get(key, {"result": {"content": [{"type": "text", "text": f"called:{key}"}]}})
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self):
        self.closed = True


def fake_child(**kw) -> Any:
    """A FakeChild typed as Any, so it can stand where the gateway expects a Child."""
    return FakeChild(**kw)


def text(result):
    return result["content"][0]["text"]


class Routing(Base):
    def gateway(self, resolve=None, legacy_child=None, mode="all"):
        g = gateway.Gateway()
        g.resolve, g.legacy, g.started, g.upstream_mode = resolve, legacy_child, True, mode
        g.tools_list()
        return g

    def call(self, g, name, args=None):
        return g._call_tool({"name": name, "arguments": args or {}})

    def test_edit_tools_run_through_dispatch(self):
        self.use(FakeResolve(sample_items()))
        r = self.call(self.gateway(), "edit__timeline_summary")
        self.assertFalse(r["isError"])
        self.assertEqual(json.loads(text(r))["timeline"], "T")

    def test_a_failed_edit_is_an_error_result(self):
        with mock.patch.object(dispatch, "run", lambda name, args: outcome.op("failed", False, reason="no")):
            r = self.call(self.gateway(), "edit__timeline_summary")
        self.assertTrue(r["isError"])
        self.assertEqual(json.loads(text(r))["reason"], "no")

    def test_an_exception_in_an_edit_tool_is_an_error_result(self):
        with mock.patch.object(dispatch, "run", side_effect=RuntimeError("boom")):
            r = self.call(self.gateway(), "edit__timeline_summary")
        self.assertEqual((r["isError"], text(r)), (True, "RuntimeError: boom"))

    def test_media_tools_run_in_this_process(self):
        with mock.patch.object(media, "run_media_tool", lambda name, args: {"tool": name, "path": args["path"]}):
            r = self.call(self.gateway(), "media__probe_media", {"path": "a.mp4"})
        self.assertEqual(json.loads(text(r)), {"tool": "probe_media", "path": "a.mp4"})

    def test_a_media_error_is_an_error_result(self):
        r = self.call(self.gateway(), "media__probe_media", {"path": "missing.mp4"})
        self.assertTrue(r["isError"])
        self.assertTrue(text(r).startswith("FileNotFoundError: "), text(r))

    def test_unknown_tool(self):
        r = self.call(self.gateway(), "nothing__here")
        self.assertEqual((r["isError"], text(r)), (True, "Unknown tool: nothing__here"))

    def test_routes_are_built_when_the_client_skipped_tools_list(self):
        g = gateway.Gateway()
        g.legacy, g.started = fake_child(), True
        self.assertEqual(text(self.call(g, "legacy__hello")), "called:hello")

    def test_a_backend_that_went_away(self):
        g = self.gateway(legacy_child=FakeChild())
        g.legacy = None
        r = self.call(g, "legacy__hello")
        self.assertEqual((r["isError"], text(r)), (True, "The legacy backend is not available."))

    def test_a_child_error_reply_is_an_error_result(self):
        child = FakeChild(replies={"hello": {"error": {"code": -32000, "message": "broke"}}})
        r = self.call(self.gateway(legacy_child=child), "legacy__hello")
        self.assertTrue(r["isError"])
        self.assertIn("broke", text(r))

    def test_legacy_writes_are_audited_with_their_outcome_and_reads_are_not(self):
        child = FakeChild(tools=("hello", "bad", "get_state"),
                          replies={"bad": {"result": {"isError": True, "content": [{"type": "text", "text": "x"}]}}})
        g, logged = self.gateway(legacy_child=child), []
        with mock.patch.object(audit, "log_audit", lambda tool, args, status: logged.append((tool, status))):
            for name in ("legacy__hello", "legacy__bad", "legacy__get_state"):
                self.call(g, name)
        self.assertEqual(logged, [("legacy__hello", "success"), ("legacy__bad", "failed")])

    def test_resolve_tools_are_forwarded(self):
        g = self.gateway(resolve=FakeChild(tools=("knowledge",)))
        self.assertEqual(text(self.call(g, "resolve__knowledge", {"q": 1})), "called:knowledge")
        self.assertEqual(g.resolve.calls[-1], ("tools/call", {"name": "knowledge", "arguments": {"q": 1}}))


class Forward(unittest.TestCase):
    def test_without_upstream_lists_are_empty_and_reads_are_errors(self):
        g = gateway.Gateway()
        g.started = True
        self.assertEqual(g.handle({"method": "resources/list"}), {"resources": []})
        self.assertEqual(g.handle({"method": "prompts/get", "params": {"name": "x"}}),
                         {"_rpc_error": {"code": -32601, "message": "upstream not installed"}})

    def test_with_upstream_results_and_errors_are_passed_on(self):
        g = gateway.Gateway()
        g.started = True
        g.resolve = fake_child(replies={"resources/list": {"result": {"resources": [{"uri": "a"}]}},
                                       "prompts/get": {"error": {"code": 7, "message": "no"}}})
        self.assertEqual(g.handle({"method": "resources/list"}), {"resources": [{"uri": "a"}]})
        self.assertEqual(g.handle({"method": "prompts/get"}), {"_rpc_error": {"code": 7, "message": "no"}})

    def test_an_unknown_method_raises_lookup_error(self):
        g = gateway.Gateway()
        g.started = True
        with self.assertRaises(LookupError):
            g.handle({"method": "sampling/create"})


class Startup(unittest.TestCase):
    def start(self, resolve, legacy_child=None, env=None, argv=("unified_server.py",)):
        g = gateway.Gateway()
        with (mock.patch.object(gateway.engine, "make_children", lambda: (resolve, legacy_child or FakeChild())),
              mock.patch.dict(os.environ, env or {}), mock.patch.object(gateway.sys, "argv", list(argv)),
              mock.patch.object(gateway.sys, "stderr", io.StringIO()) as err):
            if not env:
                os.environ.pop("RCE_UPSTREAM_TOOLS", None)
            g.start("2025-03-26")
        self.stderr = err.getvalue()
        return g

    def test_a_child_that_fails_to_start_is_dropped(self):
        broken = FakeChild(label="upstream Resolve", fail_start=True)
        g = self.start(broken)
        self.assertIsNone(g.resolve)
        self.assertTrue(broken.closed)
        self.assertIn("upstream Resolve failed to start: no such program", self.stderr)
        self.assertEqual(g.upstream_mode, "offline")

    def test_resolve_not_running_is_offline_without_asking_for_the_version(self):
        up = FakeChild(replies={"resolve_control:runtime_mode": {"result": {"content": [
            {"type": "text", "text": json.dumps({"running": False})}]}}})
        g = self.start(up)
        self.assertEqual(g.upstream_mode, "offline")
        self.assertEqual([c[1]["arguments"]["action"] for c in up.calls], ["runtime_mode"])  # get_version may launch it

    def test_a_version_error_is_offline(self):
        g = self.start(FakeChild(replies={"resolve_control:get_version": {"result": {"isError": True}}}))
        self.assertEqual(g.upstream_mode, "offline")

    def test_a_working_connection_is_all(self):
        self.assertEqual(self.start(FakeChild()).upstream_mode, "all")

    def test_an_exception_while_asking_is_offline(self):
        g = self.start(FakeChild(replies={"resolve_control:runtime_mode": TimeoutError("slow")}))
        self.assertEqual(g.upstream_mode, "offline")

    def test_the_mode_can_be_forced(self):
        up = FakeChild()
        self.assertEqual(self.start(up, env={"RCE_UPSTREAM_TOOLS": "offline"}).upstream_mode, "offline")
        self.assertEqual(self.start(up, argv=("x", "--upstream-tools=all")).upstream_mode, "all")
        self.assertEqual(up.calls, [], "a forced mode asks nothing")

    def test_offline_lists_only_the_offline_upstream_tools(self):
        g = self.start(FakeChild(tools=("knowledge", "timeline")), env={"RCE_UPSTREAM_TOOLS": "offline"})
        names = {t["name"] for t in g.tools_list()["tools"]}
        self.assertIn("resolve__knowledge", names)
        self.assertNotIn("resolve__timeline", names)

    def test_start_runs_once(self):
        g = self.start(FakeChild())
        with mock.patch.object(gateway.engine, "make_children", side_effect=AssertionError("started again")):
            g.start("2025-03-26")


def run_main(module, lines, argv=("server.py",)):
    """Run a server's main() on these input lines; returns its replies, one dict per output line."""
    out = io.StringIO()
    with (mock.patch.object(module.sys, "stdin", io.StringIO("".join(line + "\n" for line in lines))),
          mock.patch.object(module.sys, "stdout", out), mock.patch.object(module.sys, "argv", list(argv)),
          mock.patch.object(module.sys, "stderr", io.StringIO())):
        module.main()
    return [json.loads(line) for line in out.getvalue().splitlines()]


def rpc(i, method, params=None):
    return json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}})


class GatewayMain(Base):
    def setUp(self):
        patch = mock.patch.object(gateway.engine, "make_children", lambda: (None, None))  # no child processes
        patch.start()
        self.addCleanup(patch.stop)

    def test_one_reply_per_request(self):
        replies = run_main(gateway, [
            "",  # skipped
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),  # a notification: no reply
            rpc(1, "initialize", {"protocolVersion": "2025-03-26"}),
            rpc(2, "notifications/initialized"),  # with an id, but nothing to answer
            rpc(3, "ping"),
            rpc(4, "sampling/create"),
            rpc(5, "resources/read", {"uri": "x"}),
        ])
        self.assertEqual([r["id"] for r in replies], [1, 3, 4, 5])
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "resolve-creative-editor")
        self.assertEqual(replies[1]["result"], {})
        self.assertEqual(replies[2]["error"], {"code": -32601, "message": "sampling/create"})
        self.assertEqual(replies[3]["error"], {"code": -32601, "message": "upstream not installed"})

    def test_an_exception_in_a_handler_is_a_server_error(self):
        with mock.patch.object(gateway.Gateway, "_call_tool", side_effect=RuntimeError("boom")):
            replies = run_main(gateway, [rpc(1, "tools/call", {"name": "edit__doctor"})])
        self.assertEqual(replies, [{"jsonrpc": "2.0", "id": 1,
                                    "error": {"code": -32000, "message": "RuntimeError: boom"}}])

    def test_bad_input_gets_an_error_reply_and_the_gateway_goes_on(self):  # docs/ISSUES.md C-08
        replies = run_main(gateway, ["{not json", "[1, 2]", rpc(1, "ping")])
        self.assertEqual(replies, [
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}},
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request: not a JSON object"}},
            {"jsonrpc": "2.0", "id": 1, "result": {}}])

    def test_doctor_prints_the_diagnostics(self):
        out = io.StringIO()
        with (mock.patch.object(diagnostics, "doctor", lambda: {"bridge": "connected"}),
              mock.patch.object(gateway.sys, "argv", ["unified_server.py", "--doctor"]),
              mock.patch.object(gateway.sys, "stdout", out)):
            gateway.main()
        report = json.loads(out.getvalue())
        self.assertEqual(report["bridge"], "connected")
        self.assertEqual(report["pinned_commit"], gateway.engine.PINNED_COMMIT)
        self.assertIn("upstream_python_exists", report)


class LegacyBridgeTools(Base):
    def test_a_bridge_result_is_returned_as_json(self):
        self.use(lambda op, args, **kw: {"ok": True, "result": {"op": op, "args": args}})
        r = legacy.run_tool("get_state", {"x": 1})
        self.assertEqual(json.loads(text(r)), {"op": "get_state", "args": {"x": 1}})
        self.assertNotIn("isError", r)

    def test_a_bridge_refusal_or_failure_is_an_error_result(self):
        for fake, want in ((lambda op, args, **kw: {"ok": False, "error": "no timeline"}, "no timeline"),
                           (lambda op, args, **kw: {"ok": False}, "unknown error")):
            with self.subTest(want=want):
                self.use(fake)
                self.assertEqual((legacy.run_tool("get_state", {})["isError"], text(legacy.run_tool("get_state", {}))),
                                 (True, want))

    def test_an_unreachable_bridge_is_an_error_result(self):
        def down(op, args, **kw):
            raise ConnectionError("Bridge not running")
        self.use(down)
        r = legacy.run_tool("get_state", {})
        self.assertEqual((r["isError"], text(r)), (True, "Bridge not running"))

    def test_export_frame_returns_the_image(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        png = os.path.join(folder.name, "frame.png")
        with open(png, "wb") as f:
            f.write(b"\x89PNG fake")
        self.use(lambda op, args, **kw: {"ok": True, "result": {"path": png}})
        r = legacy.run_tool("export_frame", {"timecode": "01:00:00:00"})
        self.assertEqual(r["content"], [{"type": "image", "data": base64.b64encode(b"\x89PNG fake").decode(),
                                         "mimeType": "image/png"}])

    def test_an_unreadable_frame_is_an_error_result(self):
        self.use(lambda op, args, **kw: {"ok": True, "result": {"path": "missing.png"}})
        r = legacy.run_tool("export_frame", {})
        self.assertTrue(r["isError"])
        self.assertIn("frame export not readable", text(r))

    def test_an_unknown_tool_is_an_error_result(self):
        r = legacy.run_tool("format_disk", {})
        self.assertEqual((r["isError"], text(r)), (True, "unknown tool format_disk"))


class LegacyMain(Base):
    def test_errors_get_replies_and_the_server_goes_on(self):
        with mock.patch.object(legacy, "run_tool", side_effect=RuntimeError("boom")):
            replies = run_main(legacy, ["", "[1]", rpc(1, "sampling/create"), rpc(2, "tools/call", {"name": "x"}),
                                        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                                        rpc(3, "ping")])
        self.assertEqual(replies, [
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request: not a JSON object"}},
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "method not found"}},
            {"jsonrpc": "2.0", "id": 2, "error": {"code": -32000, "message": "RuntimeError: boom"}},
            {"jsonrpc": "2.0", "id": 3, "result": {}}])


if __name__ == "__main__":
    unittest.main()
