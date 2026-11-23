# Third-party notices

## davinci-resolve-mcp

- Project: https://github.com/samuelgursky/davinci-resolve-mcp
- Copyright: DaVinci Resolve MCP Contributors and Bradford Operations LLC, 2025-2026
- License: MIT
- Revision used by setup: `8f9e488a1be0d1bd8be418cc4243b695781061cd`
- The upstream repository is cloned into `vendor/davinci-resolve-mcp/` at setup time.
  Its original LICENSE file and notices remain intact. This project does not claim authorship
  of upstream code and does not modify the upstream checkout.

## Original user bridge

The files `mcp_server.py`, `resolve_bridge.lua`, and associated tests originate from the
user-provided `davinci-resolve-mcp-main.zip`. The included LICENSE file is retained unchanged.

They were later split and moved, so these files derive from them too:

- From `mcp_server.py`: `resolve_editor/paths.py`, `resolve_editor/bridge.py`, `resolve_editor/schemas/common.py`,  `resolve_editor/schemas/legacy.py` and `resolve_editor/servers/legacy.py`. `mcp_server.py` itself is now only the entry point.
- From `test_smoke.py`: `tests/smoke_bridge.py`.

`resolve_editor/media.py` and `resolve_editor/schemas/media.py` were split from `mcp_server.py` too, but that code was added after the original (commit `033e1d0`).
