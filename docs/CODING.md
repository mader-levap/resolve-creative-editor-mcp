# Coding instructions for agents

## Structure

- `resolve_editor/`: the MCP server package (`dispatch.py` runs the `edit__` tools; `session.py`, `bridge.py`, `timeline.py`, `rebuild.py` (moving and trimming a clip by rebuilding it with its settings) and the other modules are shared helpers).
  - `tools/`: the `edit__` tools, one file per area (captions, clips, placement, ripple, ...).
  - `schemas/`: tool definitions (names, arguments, descriptions) for the `edit__`, `legacy__` and `media__` tools.
  - `servers/`: the MCP servers: `gateway.py` (the one clients connect to; runs `edit__` itself and forwards the rest), `legacy.py` (the `legacy__` bridge tools and the `media__` tools), `upstream.py` (where the upstream engine and legacy server are, and how to start them), `child.py` (one child server process over stdio), `stdio.py` (what both stdio servers share: UTF-8 stdio).
- `tests/`: the shared fake Resolve (`support.py`), a fake MCP server (`fake_mcp.py`) and the Lua smoke test (`smoke_bridge.py`).
  - `unit/`: the unit tests (`test_*.py`), run by `python -m unittest`.
  - `live/`: the by-hand live test against a real Resolve (`live_resolve.py`).
- `docs/`:
  - `ISSUES.md`: known issues and live test results
  - `RESOLVE_BUGS.md`: Resolve's own bugs and quirks, each with a test to re-run on a new Resolve version
  - `PATCH_NOTES.md`
  - `MANUAL.md`
  - `THIRD_PARTY_NOTICES.md`.
- `patches/`: patches applied to the upstream engine at setup.
- `vendor/` (not in git): the upstream engine, `davinci-resolve-mcp`, installed by `setup.ps1`/`setup.sh`.
- `logs/` (not in git): setup logs.
- Root files: `resolve_bridge.lua` (the bridge that runs inside Resolve), `unified_server.py` and `mcp_server.py` (server entry points), `setup.ps1`/`setup.sh` (install), `pyproject.toml` (ruff and mypy settings).

## Coding

### General

- Always comment public classes and functions.

### Modifying scripts and mcp

When you encounter issues with doing tasks with existing tools, consider if it is possible to add new tool and/or fix existing script or tool. Never add/modify/delete script or tool without explicit permission of user.

### Bridge

After modification of `resolve_bridge.lua` script, copy it to **both** places it runs from, then reload it with the bridge's `reload_bridge` op:
- `%USERPROFILE%\resolve-claude-bridge\resolve_bridge.lua` (run by the console command below and by `reload_bridge`)
- `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\resolve_bridge.lua` (run by Workspace > Scripts > resolve_bridge in Resolve)

If the reload fails or the bridge stops answering, ask user to restart script in DaVinci's console (or the menu below):
```lua
fusion:RunScript(os.getenv("USERPROFILE").."\\resolve-claude-bridge\\resolve_bridge.lua")
```
or from the menu: `Workspace > Scripts > resolve_bridge`.

Bridge calls from all processes take turns through `bridge.lock` in the bridge folder (`bridge.call_bridge`). Never write `request.lua` another way. "bridge busy" means another client held it for 60 s and nothing was sent; retrying is safe.

`reload_bridge` only works while the bridge is running. After Resolve starts, the user has to start the bridge once (console command or menu); no tool can do that.

If a call says the bridge acknowledged an op and then stopped answering, or that it is still stuck (docs/ISSUES.md I-22): the bridge is stuck inside a Resolve call. Ask the user to restart it (menu or console; this works while the old copy is stuck, no Resolve restart needed), then run `edit__doctor`: `previous_run_stuck` names the op and step it stopped in. The stuck op may have made its change, so read the timeline back before writing again. Report the `previous_run_stuck` details in docs/ISSUES.md I-22.

### MCP server and tools

The code is the `resolve_editor` package: `tools/` (one file per area), `dispatch.py`, `schemas/`, `servers/`. Import its modules, not names from them (`session.pin`, `bridge.call_bridge()`): a copied name doesn't see the timeline pin or the test fakes.

New or changed `edit__` tools need the MCP server restarted. Until then they can be run by importing `resolve_editor.dispatch` in a Python script and calling `run(name, args)`.

Ask user to reconnect with tool via:
```bash
/mcp
```

### Testing changes

- Create tests first, fix code after, ensuring tests actually catch bugs.
- Run from the repo root: `python -m unittest`, one area with `python -m unittest tests.unit.test_batch`, the Lua smoke test with `python tests/smoke_bridge.py`, the linter with `python -m ruff check .` and the type checker with `python -m mypy` (settings for both in `pyproject.toml`). A new unit test file goes in `tests/unit/` and imports `tests.support` before `resolve_editor`.
- Coverage (to find untested code, not a target to reach): `python -m coverage run -m unittest`, then `python -m coverage combine` and `python -m coverage report`. It also measures the servers the tests start as processes, so a test must stop a server by closing its stdin, not by killing it, or that process's data is lost.
- The live test (`python tests/live/live_resolve.py`, Resolve open, bridge running) runs every area in its own `_RCE_LIVE_<time>` bin, deletes the bin with everything in it at the end and makes your bin current again; `--only captions,markers` runs some (areas: bins, clips, ripple, transitions, markers, captions, reads, in that order; a failed bins check skips the rest).
- In DaVinci, test new Resolve behaviour or code modification on a scratch timeline named `_RCE_...`, never on the user's timeline. Work in a scratch bin: remember `current_bin` from `get_state`, `create_bin` and `use_bin` an `_RCE_...` bin, and at the end `use_bin` the remembered bin and `delete_bin` the scratch one with `with_contents=true`. Otherwise new clips, timelines and backups land in the user's current bin. Pass `folder` set to the scratch bin to `edit__add_captions`, or the caption timelines go to the shared `Captions (Resolve Creative Editor)` bin, which holds the user's real captions.
- If a call fails, read the timeline back (`edit__inspect_range`) before retrying: a failed insert may or may not have left something behind.

## Commits

Never commit/push without permission.
