"""Request and reply transport to resolve_bridge.lua running inside Resolve.

Transport: request.lua in %USERPROFILE%\\resolve-claude-bridge. Replies come back through Fusion.prefs
(Resolve 21.1 and older) or through reply.csv, a metadata export of the bridge's token clip (Resolve 21.2+).
"""
import contextlib
import json
import os
import re
import struct
import sys
import threading
import time
import uuid
import zlib
from collections.abc import Iterator
from typing import IO, Any

from . import paths

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

NOT_RUNNING = ("Bridge not running. In Resolve open Workspace > Console (Lua tab) and run "
               '(Resolve 21.2+): fusion:RunScript(os.getenv("USERPROFILE")'
               '.."\\\\resolve-claude-bridge\\\\resolve_bridge.lua") '
               '(Resolve 21.1 and older): dofile(os.getenv("USERPROFILE")'
               '.."\\\\resolve-claude-bridge\\\\resolve_bridge.lua")')

RESTART = ("Ask the user to restart the bridge (Resolve: Workspace > Scripts > resolve_bridge, or the console "
           "command), then run edit__doctor and read the timeline back before writing again.")


def hang_file() -> str:
    """Written when the bridge acked a request and never answered it, removed by the next answer
    (docs/ISSUES.md I-22)."""
    return os.path.join(paths.DIR, "bridge_hang.json")


def read_hang() -> dict[str, Any] | None:
    """The record of the last hang (op, time, request id), or None when there is none or it can't be read."""
    try:
        with open(hang_file(), encoding="utf-8") as f:
            got = json.load(f)
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def _not_running() -> ConnectionError:
    hang = read_hang()
    if not hang:
        return ConnectionError(NOT_RUNNING)
    return ConnectionError(f"The bridge is still stuck since it stopped answering {hang.get('op')} at "
                           f"{hang.get('at')}: it doesn't take requests until it is restarted. {RESTART}")


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
    """`s` as a Lua long string literal ([[...]], [=[...]=], ...), with enough = signs that `s` can't close it."""
    n = 0
    while "]" + "=" * n + "]" in s:
        n += 1
    return "[" + "=" * n + "[" + s + "]" + "=" * n + "]"


class BridgeBusy(ConnectionError):
    """Another process kept the bridge for the whole wait. Nothing was sent."""


def _lock(f: IO[bytes]) -> None:
    f.seek(0)
    if sys.platform == "win32":
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(f: IO[bytes]) -> None:
    f.seek(0)
    if sys.platform == "win32":
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


WAIT_MARK = "bridge.wait."  # + pid.thread: a client waiting for the lock touches it on every try
FRESH_MARK = 0.5  # older marks are from a waiter that gave up or died
_released_at = float("-inf")  # when this process last let go of the lock


def _others_waiting(own: str) -> bool:
    now = time.time()
    for name in os.listdir(paths.DIR):
        path = os.path.join(paths.DIR, name)
        if name.startswith(WAIT_MARK) and path != own:
            with contextlib.suppress(OSError):
                if now - os.path.getmtime(path) < FRESH_MARK:
                    return True
    return False


@contextlib.contextmanager
def _bridge_lock(wait: float) -> Iterator[None]:
    """One bridge call at a time across processes: every client shares request.lua and the reply slot
    (docs/ISSUES.md I-15). The OS drops the lock if the process dies.

    The OS doesn't queue waiters, so a client calling back to back (a long batch) would take the lock again before
    a waiter polling every 50 ms sees it free. Waiters leave a mark, and a client that has just let go steps aside
    for a moment when it sees one."""
    global _released_at
    own = os.path.join(paths.DIR, f"{WAIT_MARK}{os.getpid()}.{threading.get_ident()}")
    if time.monotonic() - _released_at < 0.2 and _others_waiting(own):
        time.sleep(0.15)
    with open(os.path.join(paths.DIR, "bridge.lock"), "a+b") as f:
        deadline = time.monotonic() + wait
        try:
            while True:
                try:
                    _lock(f)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise BridgeBusy(f"bridge busy: another client has been using it for {wait:g} s; nothing "
                                         "was sent. Try again; the bridge itself is running") from None
                    with contextlib.suppress(OSError), open(own, "a"):
                        os.utime(own)
                    time.sleep(0.05)
        finally:
            with contextlib.suppress(OSError):
                os.remove(own)
        try:
            yield
        finally:
            _unlock(f)
            _released_at = time.monotonic()


def _put_request(tmp: str, req_path: str) -> None:
    """Move the request into place. Resolve may still be reading the previous one for a moment."""
    for attempt in range(40):
        try:
            os.replace(tmp, req_path)
            return
        except PermissionError:
            if attempt == 39:
                with contextlib.suppress(OSError):
                    os.remove(tmp)
                raise
            time.sleep(0.05)


# The timeout allows for Resolve stalling a few seconds (e.g. LUT rescans).
def call_bridge(op: str, args: dict[str, Any], timeout: float = 120, ack_timeout: float = 15,
                timeline: dict[str, Any] | None = None, lock_timeout: float = 60) -> dict[str, Any]:
    """Send one op to the bridge and wait for its reply. Holds the bridge lock from writing the request to
    cleanup; if another client holds it longer than lock_timeout, raises BridgeBusy without sending anything."""
    with _bridge_lock(lock_timeout):
        return _call(op, args, timeout, ack_timeout, timeline)


def _clear_hang() -> None:
    with contextlib.suppress(OSError):
        os.remove(hang_file())


def _call(op: str, args: dict[str, Any], timeout: float, ack_timeout: float,
          timeline: dict[str, Any] | None) -> dict[str, Any]:
    req_path = os.path.join(paths.DIR, "request.lua")
    rid = uuid.uuid4().hex
    ensure_token_png()
    # ts lets the bridge refuse a leftover request instead of running it again (see resolve_bridge.lua main loop).
    # Taken after the lock: the bridge drops requests over 60 s old.
    request = {"id": rid, "ts": int(time.time()), "op": op, "args": args}
    if timeline:
        request["timeline"] = timeline  # {project, name}: the bridge runs the op there or not at all
    body = lua_long_string(json.dumps(request, ensure_ascii=False))
    # 21.1 and older load this with loadfile and use the returned string; 21.2+ runs it with
    # fusion:RunScript, which cannot return values, so it also hands the JSON over with fusion:SetData.
    tmp = os.path.join(paths.DIR, f"request.{rid}.tmp")  # own name, also against clients without the lock
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("local s = " + body + "\n"
                "if fusion and fusion.SetData then fusion:SetData(\"claude_bridge_req\", s) end\n"
                "return s\n")
    _put_request(tmp, req_path)
    try:
        start, acked = time.time(), False
        while time.time() - start < timeout:
            got, payload = read_reply(rid)
            if got == rid:
                if payload:
                    try:
                        answer = json.loads(bytes.fromhex(payload).decode("utf-8"))
                    except ValueError:  # caught mid-write
                        pass
                    else:
                        _clear_hang()
                        return answer
                acked = True
            if not acked and time.time() - start > ack_timeout:
                raise _not_running()
            time.sleep(0.05)
        if not acked:
            raise _not_running()
        # Acked, then silence: the bridge's single loop is stuck inside a Resolve call (docs/ISSUES.md I-22).
        at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start))
        with contextlib.suppress(OSError), open(hang_file(), "w", encoding="utf-8") as f:
            json.dump({"op": op, "at": at, "request": rid}, f)
        raise TimeoutError(f"The bridge acknowledged {op} at {at} and then stopped answering for {timeout:g} s: it is "
                           f"probably stuck inside a Resolve call. If {op} changes anything, it may have been made. "
                           + RESTART)
    finally:
        with contextlib.suppress(OSError):
            os.remove(req_path)
