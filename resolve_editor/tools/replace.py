"""Moving and trimming by settings-preserving replacement (rebuild.py)."""
from collections.abc import Callable
from typing import Any

from .. import outcome, rebuild, session, timeline


def _replace_tool(a: dict[str, Any], new_range: Callable[[session.Item], tuple[int, int, int, int]],
                  verb: str) -> dict[str, Any]:
    if not session.get_state().get("clip_markers_by_source"):
        return outcome.blocked("the Resolve bridge is older than this server and would drop clip markers; restart "
                               "the bridge (Workspace > Scripts > resolve_bridge)")
    plan = rebuild.plan(a["item_id"], a.get("include_linked", True), new_range)
    if isinstance(plan, str):
        return outcome.blocked(plan)
    rows = [{"item": p["item"]["name"], "track": timeline.track_label(p["item"]["track_type"], p["track"]),
             "from": [session.to_tc(p["item"]["start"]), p["item"]["duration"]],
             "to": [session.to_tc(p["record"]), p["last"] - p["first"]]}
            for p in plan]
    if not a.get("confirm"):
        return outcome.preview({verb: rows,
                                "method": "replacement built and settings copied before the original is removed"},
                               ["keyframes are not copied", "a backup timeline is made first"])
    return rebuild.run(plan, a.get("backup", True))


def move_item(a: dict[str, Any]) -> dict[str, Any]:
    """edit__move_item: preview, then move a clip (and its linked items) by rebuilding it at the new place."""
    target = session.to_frame(a["record"])
    root = next((x for x in session.items() if x["id"] == a["item_id"]), None)
    if not root:
        return outcome.blocked(f"timeline item not found: {a['item_id']}")
    shift = target - root["start"]
    return _replace_tool(a, lambda it: (it["source_start"], it["source_start"] + it["duration"], it["start"] + shift,
                                        a.get("track_index") or it["track"] if it["id"] == a["item_id"]
                                        else it["track"]),
                         "move")


def trim_item(a: dict[str, Any]) -> dict[str, Any]:
    """edit__trim_item: preview, then trim frames off either end of a clip by rebuilding it."""
    head, tail = a.get("head_frames") or 0, a.get("tail_frames") or 0
    if not head and not tail:
        return outcome.blocked("give head_frames and/or tail_frames")
    return _replace_tool(a, lambda it: (it["source_start"] + head, it["source_start"] + it["duration"] - tail,
                                        it["start"] + head, it["track"]), "trim")
