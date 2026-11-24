"""A minimal MCP server over stdio for the gateway tests. Its tools are named on the command line (default: hello).
With FAKE_MCP_EXIT_FILE set, it creates that file when its input ends, which a killed process never does."""
import json
import os
import sys

NAMES = sys.argv[1:] or ["hello"]

for line in sys.stdin:
    msg=json.loads(line)
    if "id" not in msg:
        continue
    method=msg.get("method")
    if method=="initialize":
        result={"protocolVersion":msg["params"].get("protocolVersion","2025-03-26"),"capabilities":{"tools":{},"resources":{},"prompts":{}},"serverInfo":{"name":"fake","version":"1"}}
    elif method=="tools/list":
        result={"tools":[{"name":n,"description":"fake tool","inputSchema":{"type":"object","properties":{}}}
                         for n in NAMES]}
    elif method=="tools/call":
        args=msg["params"].get("arguments") or {}  # echoed, so a test sees what was forwarded
        text="called:"+msg["params"]["name"]+(" "+json.dumps(args) if args else "")
        result={"content":[{"type":"text","text":text}]}
    elif method=="resources/list":
        result={"resources":[]}
    elif method=="prompts/list":
        result={"prompts":[]}
    else:
        result={}
    print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":result}),flush=True)

if os.environ.get("FAKE_MCP_EXIT_FILE"):
    open(os.environ["FAKE_MCP_EXIT_FILE"], "w").close()
