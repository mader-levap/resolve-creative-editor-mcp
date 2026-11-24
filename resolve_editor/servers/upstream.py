"""Where the upstream engine and the legacy server are, and the child processes to start for them."""
import json
import os
import pathlib
import sys

from . import child

ROOT = pathlib.Path(__file__).resolve().parents[2]  # the repo
UPSTREAM_REPO = pathlib.Path(os.environ.get("RESOLVE_MCP_REPO", ROOT / "vendor" / "davinci-resolve-mcp")).resolve()
UPSTREAM_SERVER = pathlib.Path(os.environ.get("RESOLVE_MCP_SERVER", UPSTREAM_REPO / "src" / "server.py")).resolve()
LEGACY_SERVER = ROOT / "mcp_server.py"
PINNED_COMMIT = "8f9e488a1be0d1bd8be418cc4243b695781061cd"


def upstream_python() -> pathlib.Path:
    override = os.environ.get("RESOLVE_MCP_PYTHON")
    if override:
        return pathlib.Path(override).resolve()
    if os.name == "nt":
        return UPSTREAM_REPO / "venv" / "Scripts" / "python.exe"
    return UPSTREAM_REPO / "venv" / "bin" / "python"


def _command_from_env(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return default
    value = json.loads(raw)
    if not isinstance(value, list) or not value or not all(isinstance(x, str) for x in value):
        raise ValueError(f"{name} must be a JSON array of command strings")
    return value


def make_children() -> tuple[child.Child | None, child.Child]:
    legacy_cmd = _command_from_env("LEGACY_MCP_COMMAND", [sys.executable, str(LEGACY_SERVER)])
    legacy = child.Child("legacy bridge", legacy_cmd, ROOT)
    upstream_override = os.environ.get("RESOLVE_MCP_COMMAND")
    engine_python = upstream_python()
    if not upstream_override and not (UPSTREAM_SERVER.is_file() and engine_python.is_file()):
        sys.stderr.write("upstream engine not installed; continuing with legacy__, media__ and edit__\n")
        return None, legacy
    upstream_cmd = _command_from_env("RESOLVE_MCP_COMMAND", [str(engine_python), str(UPSTREAM_SERVER)])
    return child.Child("upstream Resolve", upstream_cmd, ROOT if upstream_override else UPSTREAM_REPO), legacy
