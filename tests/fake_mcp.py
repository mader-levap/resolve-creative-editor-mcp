"""A minimal MCP server over stdio for the gateway and Child tests. Its tools are named on the command line (default:
hello). Calling the tool `slow` answers after FAKE_MCP_SLOW seconds (default 1); calling `exit` ends the process without
an answer.

Environment switches:
- FAKE_MCP_EXIT_FILE: create that file when the input ends, which a killed process never does.
- FAKE_MCP_NOISE: write a line that isn't JSON and a message without an id before every answer.
- FAKE_MCP_INIT_ERROR: answer initialize with an error.
- FAKE_MCP_IGNORE_EOF: keep running for a minute after the input ends, so only terminate() stops it.
"""
import json
import os
import sys
import time

NAMES = sys.argv[1:] or ["hello"]

for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    method = msg.get("method")
    reply: dict = {"jsonrpc": "2.0", "id": msg["id"]}
    if method == "initialize" and os.environ.get("FAKE_MCP_INIT_ERROR"):
        reply["error"] = {"code": -32603, "message": "cannot start"}
    elif method == "initialize":
        reply["result"] = {"protocolVersion": msg["params"].get("protocolVersion", "2025-03-26"),
                           "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                           "serverInfo": {"name": "fake", "version": "1"}}
    elif method == "tools/list":
        reply["result"] = {"tools": [{"name": n, "description": "fake tool",
                                      "inputSchema": {"type": "object", "properties": {}}} for n in NAMES]}
    elif method == "tools/call":
        name = msg["params"]["name"]
        if name == "exit":
            sys.exit(3)
        if name == "slow":
            time.sleep(float(os.environ.get("FAKE_MCP_SLOW") or 1))
        args = msg["params"].get("arguments") or {}  # echoed, so a test sees what was forwarded
        reply["result"] = {"content": [{"type": "text", "text": "called:" + name + (" " + json.dumps(args) if args
                                                                                   else "")}]}
    elif method == "resources/list":
        reply["result"] = {"resources": []}
    elif method == "prompts/list":
        reply["result"] = {"prompts": []}
    else:
        reply["result"] = {}
    if os.environ.get("FAKE_MCP_NOISE"):
        print("starting up, not JSON", flush=True)
        print(json.dumps({"jsonrpc": "2.0", "method": "notifications/message", "params": {}}), flush=True)
    print(json.dumps(reply), flush=True)

if os.environ.get("FAKE_MCP_EXIT_FILE"):
    open(os.environ["FAKE_MCP_EXIT_FILE"], "w").close()
if os.environ.get("FAKE_MCP_IGNORE_EOF"):
    time.sleep(60)
