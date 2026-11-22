"""Single stdio MCP gateway for the upstream Resolve MCP and the user's legacy bridge.

Tool namespaces:
  resolve__* -> upstream compound Resolve MCP
  legacy__*  -> original Lua bridge MCP
  media__*   -> original FFmpeg/transcription/contact-sheet tools (run in this process)
  edit__*    -> verified high-level editing tools built on the bridge (run in this process)
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from .. import audit, dispatch, media, session
from ..schemas import edit as edit_schema
from ..schemas import legacy as legacy_schema
from ..tools import diagnostics
from . import child as child_process
from . import upstream as engine

# Upstream tools that work without a live scripting connection, so they stay useful on free Resolve.
OFFLINE_UPSTREAM = {"knowledge", "media_analysis", "setup"}
# Legacy tools that destroy work or start long jobs need an explicit confirm=true.
GUARDED_LEGACY = {"delete_items", "start_render"}
READ_ONLY_LEGACY = {"get_state", "list_timelines", "list_media", "list_timeline_items", "list_markers", "probe_color",
                    "export_frame", "list_render_presets", "render_status", "goto_timecode", "open_page",
                    "set_current_timeline"}
INSTRUCTIONS = """Controls DaVinci Resolve. On free Resolve use edit__ (preferred) and legacy__; resolve__ timeline tools need Studio.
Start with edit__timeline_summary (the user may have edited by hand), then edit__inspect_range for the part you will change.
Destructive edit__ tools return a preview first: show it to the user, then repeat with confirm=true. Use edit__batch for
several changes. Never rebuild a whole timeline, never delete clips without asking, never render unless told to.
Do not mix legacy__ and resolve__ edits on one timeline. Read resolve__knowledge for editorial, colour and audio craft.
You cannot hear audio: say so rather than implying it."""  # noqa: E501  (sent to the client as written)


def _prefix_tool(tool: dict[str, Any], prefix: str, warning: str = "") -> dict[str, Any]:
    result = dict(tool)
    original = result["name"]
    result["name"] = prefix + original
    if warning:
        result["description"] = (warning + "\n\n" + result.get("description", "")).strip()
    return result


def _media_tools() -> list[dict[str, Any]]:
    return [_prefix_tool(t, "media__", "Local media analysis; source files are read-only.")
            for t in legacy_schema.TOOLS if t["name"] in media.HANDLERS]


def _edit_tools() -> list[dict[str, Any]]:
    return [_prefix_tool(t, "edit__") for t in edit_schema.TOOLS]


def _run_edit_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = dispatch.run(name, args)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                "isError": result.get("_operation", {}).get("status") == "failed"}
    except Exception as exc:
        return {"isError": True, "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}]}


def _with_confirm(tool: dict[str, Any]) -> dict[str, Any]:
    schema = dict(tool.get("inputSchema") or {"type": "object", "properties": {}})
    schema["properties"] = {**schema.get("properties", {}),
                            "confirm": {"type": "boolean", "description": "Must be true. Ask the user first."}}
    schema["required"] = list(schema.get("required", [])) + ["confirm"]
    return {**tool, "inputSchema": schema}


def _run_media_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        result = media.run_media_tool(name, args)
        if name == "make_contact_sheet":
            return {"content": [
                {"type": "image", "data": result["image"], "mimeType": result["mimeType"]},
                {"type": "text",
                 "text": json.dumps({k:v for k,v in result.items() if k not in {"image","mimeType"}}, indent=2)}
            ]}
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}
    except Exception as exc:
        return {"isError": True, "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}]}


class Gateway:
    def __init__(self):
        self.resolve: child_process.Child | None = None
        self.legacy: child_process.Child | None = None
        self.tool_routes: dict[str, tuple[str, str]] = {}
        self.started = False
        self.protocol = "2025-03-26"
        self.upstream_mode = "offline"

    def _start_child(self, child: child_process.Child | None, protocol: str) -> child_process.Child | None:
        if child is None:
            return None
        try:
            child.start(protocol)
            return child
        except Exception as exc:
            sys.stderr.write(f"{child.label} failed to start: {exc}\n")
            child.close()
            return None

    def _detect_upstream_mode(self) -> str:
        """all = every resolve__ tool; offline = only those that work without scripting. Never launches Resolve."""
        forced = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--upstream-tools=")),
                      os.environ.get("RCE_UPSTREAM_TOOLS", "auto"))
        if forced in {"all", "offline"} or not self.resolve:
            return forced if self.resolve else "offline"
        def ask(action: str) -> dict[str, Any]:
            return self.resolve.request(  # type: ignore[union-attr]  # only called after the check above
                "tools/call", {"name": "resolve_control", "arguments": {"action": action}}, timeout=30.0
            ).get("result", {})
        try:
            first = ask("runtime_mode")
            try:
                if json.loads(first["content"][0]["text"]).get("running") is False:
                    return "offline"  # get_version could launch Resolve
            except (KeyError, IndexError, TypeError, ValueError):
                pass
            return "offline" if ask("get_version").get("isError") else "all"
        except Exception:
            return "offline"

    def start(self, protocol: str) -> None:
        if self.started:
            return
        self.protocol = protocol
        self.resolve, self.legacy = engine.make_children()
        self.resolve = self._start_child(self.resolve, protocol)
        self.legacy = self._start_child(self.legacy, protocol)
        self.upstream_mode = self._detect_upstream_mode()
        self.started = True

    def tools_list(self) -> dict[str, Any]:
        tools: list[dict[str, Any]] = []
        self.tool_routes.clear()
        for tool in (self.resolve.tools if self.resolve else []):
            if self.upstream_mode == "offline" and tool["name"] not in OFFLINE_UPSTREAM:
                continue
            t = _prefix_tool(tool, "resolve__")
            tools.append(t)
            self.tool_routes[t["name"]] = ("resolve", tool["name"])
        for tool in (self.legacy.tools if self.legacy else []):
            if tool["name"] in media.HANDLERS:
                continue
            t = _prefix_tool(
                tool, "legacy__",
                "FALLBACK ONLY: prefer the matching resolve__ tool. "
                "Do not mix legacy__ and resolve__ timeline mutations in one edit."
            )
            if tool["name"] in GUARDED_LEGACY:
                t = _with_confirm(t)
            tools.append(t)
            self.tool_routes[t["name"]] = ("legacy", tool["name"])
        for tool in _media_tools():
            tools.append(tool)
            self.tool_routes[tool["name"]] = ("media", tool["name"].replace("media__", ""))
        for tool in _edit_tools():
            tools.append(tool)
            self.tool_routes[tool["name"]] = ("edit", tool["name"].replace("edit__", ""))
        return {"tools": tools}

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            requested = params.get("protocolVersion", self.protocol)
            self.start(requested)
            upstream = self.resolve.initialize_result if self.resolve else {}
            caps = dict((upstream or {}).get("capabilities", {}))
            caps["tools"] = {}
            return {"protocolVersion": (upstream or {}).get("protocolVersion", requested),
                    "capabilities": caps,
                    "instructions": INSTRUCTIONS,
                    "serverInfo": {"name": "resolve-creative-editor", "version": "1.0.0"}}
        if method == "notifications/initialized":
            # child_process.Child servers receive their own initialized notification during startup.
            return None
        if method == "ping":
            return {}
        if not self.started:
            self.start(self.protocol)
        if method == "tools/list":
            return self.tools_list()
        if method == "tools/call":
            return self._call_tool(params)
        if method in {"resources/list", "resources/read", "prompts/list", "prompts/get"}:
            return self._forward(method, params)
        raise LookupError(method)

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        route = self.tool_routes.get(name)
        if route is None:
            # Build route table on first call if host skipped tools/list.
            self.tools_list()
            route = self.tool_routes.get(name)
        if route is None:
            return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
        backend, original = route
        if backend == "media":
            return _run_media_tool(original, args)
        if backend == "edit":
            return _run_edit_tool(original, args)
        if backend == "legacy" and original in GUARDED_LEGACY:
            if args.get("confirm") is not True:
                return {"isError": True, "content": [{"type": "text", "text":
                        f"Blocked: {original} needs confirm=true. Ask the user first."}]}
            args = {k: v for k, v in args.items() if k != "confirm"}
        child = self.resolve if backend == "resolve" else self.legacy
        if child is None:
            return {"isError": True,
                    "content": [{"type": "text", "text": f"The {backend} backend is not available."}]}
        response = child.request("tools/call", {"name": original, "arguments": args}, timeout=1800.0)
        if "error" in response:
            return {"isError": True, "content": [{"type": "text", "text": str(response["error"])}]}
        result = response.get("result", {})
        if backend == "legacy" and original not in READ_ONLY_LEGACY:
            session.invalidate()
            audit.log_audit(name, args, "failed" if result.get("isError") else "success")
        return result

    def _forward(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.resolve:
            if method.endswith("/list"):
                return {method.split("/")[0]: []}
            return {"_rpc_error": {"code": -32601, "message": "upstream not installed"}}
        response = self.resolve.request(method, params)
        if "error" in response:
            return {"_rpc_error": response["error"]}
        return response.get("result", {})

    def close(self):
        if self.resolve:
            self.resolve.close()
        if self.legacy:
            self.legacy.close()


def main() -> None:
    if "--doctor" in sys.argv:
        py = engine.upstream_python()
        print(json.dumps({
            **diagnostics.doctor(),
            "upstream_repo": str(engine.UPSTREAM_REPO),
            "upstream_server_exists": engine.UPSTREAM_SERVER.is_file(),
            "upstream_python": str(py),
            "upstream_python_exists": py.is_file(),
            "legacy_server_exists": engine.LEGACY_SERVER.is_file(),
            "pinned_commit": engine.PINNED_COMMIT,
        }, indent=2))
        return

    gateway = Gateway()
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
                if "id" not in message:
                    gateway.handle(message)
                    continue
                try:
                    result = gateway.handle(message)
                    if result is None:
                        continue
                    if "_rpc_error" in result:
                        output = {"jsonrpc": "2.0", "id": message["id"], "error": result["_rpc_error"]}
                    else:
                        output = {"jsonrpc": "2.0", "id": message["id"], "result": result}
                except LookupError as exc:
                    output = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": str(exc)}}
                except Exception as exc:
                    output = {"jsonrpc": "2.0", "id": message["id"],
                              "error": {"code": -32000, "message": f"{type(exc).__name__}: {exc}"}}
                sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            except Exception as exc:
                sys.stderr.write(f"gateway error: {type(exc).__name__}: {exc}\n")
                sys.stderr.flush()
    finally:
        gateway.close()
