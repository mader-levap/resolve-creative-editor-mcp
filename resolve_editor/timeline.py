"""Timeline steps that several tools share: backup, clip lookup, collisions, appending."""
import time
from collections.abc import Collection
from typing import Any

from . import outcome, session


def snapshot_timeline(a: dict[str, Any]) -> dict[str, Any]:
    """Duplicate the current timeline as a timestamped backup and make the original current again;
    raises if Resolve doesn't go back to it."""
    current = session.get_state()["timeline"]
    if not current:
        return outcome.blocked("no current timeline")
    name = f"{current} {a.get('label') or 'backup'} {time.strftime('%Y%m%d-%H%M%S')}"
    session.call("duplicate_timeline", name=name)  # Resolve makes the copy current
    session.call("set_current_timeline", name=current)  # the bridge retries until Resolve stays on it
    session.invalidate()
    if name not in session.as_list(session.call("list_timelines")) or session.call("get_state")["timeline"] != current:
        raise RuntimeError(f"backup made, but Resolve did not return to {current}; nothing was edited")
    return outcome.op("success", True, {"created_timeline": name}, snapshot=name)


def track_label(kind: str, track: int) -> str:
    """How Resolve names a track: V2, A1."""
    return f"{kind[0].upper()}{track}"


def item_label(it: session.Item) -> str:
    """The track an item is on: V2, A1."""
    return track_label(it["track_type"], it["track"])


def markers_by_frame(listed: object) -> dict[int, Any]:
    """Markers as the bridge lists them (JSON object keyed by frame strings), keyed by int frame."""
    return {int(float(k)): v for k, v in (listed.items() if isinstance(listed, dict) else ())}


def find_clip(ref: str) -> dict[str, Any]:
    """The one Media Pool clip with this id, else with this exact name; raises unless exactly one matches."""
    hits = ([m for m in session.media_pool() if m.get("id") == ref]
            or [m for m in session.media_pool() if m.get("name") == ref])
    if len(hits) != 1:
        raise ValueError(f"need exactly one media-pool clip matching {ref!r}, found {len(hits)}")
    return hits[0]


def collides(kind: str, track: int, start: int, end: int,
             ignore: Collection[str] = ()) -> session.Item | None:
    """The first item on that track overlapping [start, end) (end exclusive), not counting transitions or the
    ids in `ignore`; None when the frames are free."""
    for x in session.items():
        if (x["track_type"] == kind and x["track"] == track and x["id"] not in ignore
                and x.get("type") != "transition" and x["start"] < end and start < x["end"]):
            return x
    return None


def append_one(media_id: str, kind: str, first: int, last: int, record: int,
               track: int) -> session.Item:
    """Place frames [first, last) of a Media Pool clip at `record` on a track and return the new item; raises
    if it didn't land there (Resolve may refuse an append without an error)."""
    session.call("append_clips", clips=[{"clip": media_id, "start_frame": first, "end_frame": last,
                                         "record_frame": record, "track_index": track,
                                         "media_type": 1 if kind == "video" else 2}])
    session.invalidate()
    for x in session.items():
        if x["track_type"] == kind and x["track"] == track and x["start"] == record and x["duration"] == last - first:
            return x
    raise RuntimeError(f"append to {kind} {track} at {record} did not land")
