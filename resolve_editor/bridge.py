"""Request and reply transport to resolve_bridge.lua running inside Resolve.

Transport: request.lua in %USERPROFILE%\\resolve-claude-bridge. Replies come back through Fusion.prefs
(Resolve 21.1 and older) or through reply.csv, a metadata export of the bridge's token clip (Resolve 21.2+).
"""
import json
import os
import re
import struct
import time
import uuid
import zlib
from typing import Any

from . import paths

NOT_RUNNING = ("Bridge not running. In Resolve open Workspace > Console (Lua tab) and run "
               '(Resolve 21.2+): fusion:RunScript(os.getenv("USERPROFILE")'
               '.."\\\\resolve-claude-bridge\\\\resolve_bridge.lua") '
               '(Resolve 21.1 and older): dofile(os.getenv("USERPROFILE")'
               '.."\\\\resolve-claude-bridge\\\\resolve_bridge.lua")')

# Resolve's Lua cannot write files, so the bridge replies via Fusion's prefs file (see resolve_bridge.lua).
PREFS = os.environ.get("RESOLVE_FUSION_PREFS") or os.path.join(
    os.environ.get("APPDATA", ""), "Blackmagic Design", "DaVinci Resolve", "Support", "Fusion", "Profiles",
    "Default", "Fusion.prefs")
RES_RE = re.compile(r'claude_bridge_res\s*=\s*"([0-9a-f]*):([0-9a-f]*)"')
# Resolve 21.2+ (no SavePrefs): the bridge writes the reply into its token clip's Comments metadata and
# exports it here with MediaPool:ExportMetadata (UTF-16 CSV).
REPLY_CSV = os.path.join(paths.DIR, "reply.csv")
TOKEN_PNG = os.path.join(paths.DIR, "bridge_token.png")
# Our reply is the only <32 hex id>:<hex> in the export. Not parsed as CSV: that has a field size limit and
# keeps reading while Resolve is still writing.
VALUE_RE = re.compile(r"(?<![0-9a-f])([0-9a-f]{32}):([0-9a-f]*)")


def _read_prefs_reply() -> tuple[str | None, str | None]:
    try:
        with open(PREFS, encoding="utf-8", errors="replace") as f:
            m = RES_RE.search(f.read())
        return (m.group(1), m.group(2)) if m else (None, None)
    except OSError:  # being rewritten
        return None, None


def _read_csv_reply() -> tuple[str | None, str | None]:
    try:
        with open(REPLY_CSV, encoding="utf-16", newline="") as f:
            m = VALUE_RE.search(f.read())
    except (OSError, UnicodeError):  # missing, or caught mid-write
        return None, None
    return (m.group(1), m.group(2)) if m else (None, None)


def read_reply(want: str | None = None) -> tuple[str | None, str | None]:
    """Latest reply from either transport; with `want`, only a reply for that request id."""
    for reader in (_read_csv_reply, _read_prefs_reply):
        got, payload = reader()
        if got is not None and (want is None or got == want):
            return got, payload
    return None, None


def ensure_token_png() -> None:
    """The 21.2+ bridge imports this 16x16 black PNG as its reply carrier; Resolve's Lua cannot create it."""
    if os.path.isfile(TOKEN_PNG):
        return

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * 16 for _ in range(16))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    with open(TOKEN_PNG + ".tmp", "wb") as f:
        f.write(png)
    os.replace(TOKEN_PNG + ".tmp", TOKEN_PNG)


def lua_long_string(s: str) -> str:
    n = 0
    while "]" + "=" * n + "]" in s:
        n += 1
    return "[" + "=" * n + "[" + s + "]" + "=" * n + "]"


# The timeout allows for Resolve stalling a few seconds (e.g. LUT rescans).
def call_bridge(op: str, args: dict[str, Any], timeout: float = 120, ack_timeout: float = 15,
                timeline: dict[str, Any] | None = None) -> dict[str, Any]:
    req_path = os.path.join(paths.DIR, "request.lua")
    rid = uuid.uuid4().hex
    ensure_token_png()
    # ts lets the bridge refuse a leftover request instead of running it again (see resolve_bridge.lua main loop).
    request = {"id": rid, "ts": int(time.time()), "op": op, "args": args}
    if timeline:
        request["timeline"] = timeline  # {project, name}: the bridge runs the op there or not at all
    body = lua_long_string(json.dumps(request, ensure_ascii=False))
    # 21.1 and older load this with loadfile and use the returned string; 21.2+ runs it with
    # fusion:RunScript, which cannot return values, so it also hands the JSON over with fusion:SetData.
    with open(req_path + ".tmp", "w", encoding="utf-8") as f:
        f.write("local s = " + body + "\n"
                "if fusion and fusion.SetData then fusion:SetData(\"claude_bridge_req\", s) end\n"
                "return s\n")
    os.replace(req_path + ".tmp", req_path)
    try:
        start, acked = time.time(), False
        while time.time() - start < timeout:
            got, payload = read_reply(rid)
            if got == rid:
                if payload:
                    try:
                        return json.loads(bytes.fromhex(payload).decode("utf-8"))
                    except ValueError:  # caught mid-write
                        pass
                acked = True
            if not acked and time.time() - start > ack_timeout:
                raise ConnectionError(NOT_RUNNING)
            time.sleep(0.05)
        raise TimeoutError(f"Resolve did not answer {op} within {timeout}s")
    finally:
        try:
            os.remove(req_path)
        except OSError:
            pass
