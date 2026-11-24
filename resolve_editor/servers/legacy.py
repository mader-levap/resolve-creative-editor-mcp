"""The legacy MCP server: forwards tool calls to the bridge and runs the media tools."""
import base64
import json
import sys
from typing import Any

from .. import bridge, media
from ..schemas import legacy as schema
from . import stdio


def run_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name in media.HANDLERS:
        return stdio.media_result(name, args)
    if name not in {t["name"] for t in schema.TOOLS}:
        return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
    try:
        res = bridge.call_bridge(name, args)
    except Exception as e:
        res = {"ok": False, "error": str(e)}
    if not res.get("ok"):
        return {"content": [{"type": "text", "text": res.get("error", "unknown error")}], "isError": True}
    content = [{"type": "text", "text": json.dumps(res.get("result"), indent=1)}]
    if name == "export_frame":
        try:
            with open(res["result"]["path"], "rb") as f:
                content = [{"type": "image", "data": base64.b64encode(f.read()).decode(), "mimeType": "image/png"}]
        except OSError as e:
            return {"content": [{"type": "text", "text": f"frame export not readable: {e}"}], "isError": True}
    return {"content": content}


def handle(msg: dict[str, Any]) -> dict[str, Any]:
    m, p = msg.get("method"), msg.get("params") or {}
    if m == "initialize":
        return {"protocolVersion": p.get("protocolVersion", "2025-03-26"), "capabilities": {"tools": {}},
                "serverInfo": {"name": "davinci-resolve", "version": "0.2.0"}}
    if m == "tools/list":
        return {"tools": schema.TOOLS}
    if m == "tools/call":
        return run_tool(p.get("name"), p.get("arguments") or {})  # type: ignore[arg-type]  # None: "unknown tool"
    if m == "ping":
        return {}
    raise LookupError(m)


def main() -> None:
    stdio.use_utf8()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:  # one bad line must not stop the server
            msg = None
        if not isinstance(msg, dict):
            out: dict[str, Any] = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        elif "id" not in msg:  # notification
            continue
        else:
            try:
                out = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)}
            except LookupError:
                out = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found"}}
            except Exception as exc:
                out = {"jsonrpc": "2.0", "id": msg["id"],
                       "error": {"code": -32000, "message": f"{type(exc).__name__}: {exc}"}}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()
