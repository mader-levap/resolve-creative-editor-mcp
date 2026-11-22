"""A minimal MCP server over stdio for the gateway tests. Its tools are named on the command line (default: hello)."""
import json
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
        result={"content":[{"type":"text","text":"called:"+msg["params"]["name"]}]}
    elif method=="resources/list":
        result={"resources":[]}
    elif method=="prompts/list":
        result={"prompts":[]}
    else:
        result={}
    print(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":result}),flush=True)
