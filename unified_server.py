#!/usr/bin/env python3
"""Single stdio MCP gateway for the upstream Resolve MCP and the user's legacy bridge (see resolve_editor/servers)."""
from resolve_editor.servers import gateway

if __name__ == "__main__":
    gateway.main()
