"""MCP server (stdio, stdlib only) that forwards tool calls to resolve_bridge.lua running inside Resolve."""
from resolve_editor.servers import legacy

if __name__ == "__main__":
    legacy.main()
