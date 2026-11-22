"""Bridge access for edit__ tools: the short-lived cache and the pin to the timeline being written.

Use it as session.pin, never `from .session import pin`: a copy would not follow the running write."""
import time
from collections.abc import Callable
from fractions import Fraction
from typing import Any, TypedDict

from . import bridge, timecode

_cache: dict[str, tuple[float, Any]] = {}
pin: dict[str, Any] | None = None  # {project, name} of the timeline the running write is bound to (see dispatch.run)
switched: set[str] = set()  # timelines the bridge had to switch back from during that write
_cached_for: tuple[Any, Any] | None = None  # (project, timeline) the cache was last checked against


class _ItemKeys(TypedDict):
    """A timeline item, as item_info in resolve_bridge.lua returns it."""
    id: str
    name: str
    start: int
    end: int
    duration: int
    track_type: str  # video or audio
    track: int


class Item(_ItemKeys, total=False):
    source_start: int  # left offset into the source; missing when Resolve can't report it
    type: str  # e.g. video, audio, transition; missing when Resolve can't report it


def invalidate() -> None:
    global _cached_for
    _cache.clear()
    _cached_for = None


def drop_if_switched() -> None:
    """Before a read: clear the cache if another project or timeline is current now (ISSUES.md I-17)."""
    global _cached_for
    state = call("get_state")
    now = (state.get("project"), state.get("timeline"))
    if now != _cached_for:
        invalidate()
    _cached_for = now
    _cache["state"] = (time.monotonic(), state)


def call(op: str, **args: Any) -> Any:
    pinned: dict[str, Any] = {"timeline": pin} if pin and op != "set_current_timeline" else {}
    res = bridge.call_bridge(op, args, **pinned)
    if res.get("switched_from"):
        switched.add(res["switched_from"])
    if not res.get("ok"):
        raise RuntimeError(res.get("error", "bridge error"))
    return res.get("result")


def _cached(key: str, fetch: Callable[[], Any], ttl: float = 3.0) -> Any:
    """Short-lived cache so one tool call (or a quick sequence) doesn't re-read the timeline. Writes invalidate it."""
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = fetch()
    _cache[key] = (time.monotonic(), value)
    return value


def as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def get_state() -> dict[str, Any]:
    return _cached("state", lambda: call("get_state"))


def clock() -> tuple[Fraction, bool, dict[str, Any]]:
    state = get_state()
    if not state.get("timeline"):
        raise RuntimeError("no current timeline")
    return (timecode.parse_fps(state["timeline_fps"]),
            str(state.get("timeline_drop_frame")) in ("1", "true", "True"), state)


def items() -> list[Item]:
    return _cached("items", lambda: as_list(call("list_timeline_items", track_type="video")) +
                   as_list(call("list_timeline_items", track_type="audio")))


def media_pool() -> list[dict[str, Any]]:
    return _cached("media", lambda: as_list(call("list_media")), ttl=10.0)


def to_frame(value: object) -> int:
    """Absolute timeline frame from an int or a timecode string."""
    if isinstance(value, bool) or value is None:
        raise ValueError("expected a frame number or timecode")
    if isinstance(value, (int, float)):
        return int(value)
    fps, drop, _ = clock()
    return timecode.tc_to_frame(str(value), fps, drop)


def to_tc(frame: int) -> str:
    fps, drop, _ = clock()
    return timecode.frame_to_tc(frame, fps, drop)
