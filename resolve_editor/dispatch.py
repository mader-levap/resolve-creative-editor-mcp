"""Entry point of the edit__ tools: run, batch and the handler table."""
from typing import Any

from . import audit, outcome, session, timeline
from .tools import audio, captions, clips, delivery, diagnostics, inspection, markers, placement, replace, ripple


def _preview_step(op: dict[str, Any]) -> dict[str, Any]:
    """One row of a batch preview. Must never change anything, so only PREVIEWABLE tools are called."""
    tool = op["tool"]
    args = dict(op.get("args") or {}, confirm=False)  # a step can't confirm itself
    transcribes = tool == "add_captions" and not args.get("segments")  # slow, and writes the transcript cache
    if tool in PREVIEWABLE and not transcribes:
        return {"tool": tool, "preview": run(tool, args)}
    del args["confirm"]
    return {"tool": tool, "args": args, "not_run": "no preview; runs when the batch is confirmed"}


DONE = ("success", "planned")  # a batch goes on only after these


def batch(a: dict[str, Any]) -> dict[str, Any]:
    ops = a["operations"]
    unknown = [o.get("tool") for o in ops if o.get("tool") not in HANDLERS or o.get("tool") == "batch"]
    if unknown:
        return outcome.blocked(f"unknown or nested tools: {unknown}")
    if not a.get("confirm"):
        rows = [_preview_step(o) for o in ops]
        unchecked = sum("not_run" in r for r in rows)
        return outcome.preview(rows, [f"{unchecked} step(s) have no preview and were not checked"] if unchecked else [])
    snapshot = timeline.snapshot_timeline({"label": "before batch"}).get("snapshot")
    results = []
    for o in ops:
        args = dict(o.get("args") or {}, confirm=True, backup=False)
        r = run(o["tool"], args)
        status = r.get("_operation", {}).get("status", "success")
        row = {"tool": o["tool"], "status": status, "reason": r.get("reason")}
        results.append(row)
        if status not in DONE:
            row.update({k: r["_operation"].get(k) for k in ("changes", "warnings")})
            break
    not_run = [o["tool"] for o in ops[len(results):]]
    ok = all(r["status"] in DONE for r in results)  # the loop only breaks after a step that isn't
    why = {} if ok else {"reason": f"stopped at step {len(results)} of {len(ops)} ({row['tool']}: {row['status']}); "
                                   f"{len(not_run)} not run. Read the timeline back, don't repeat the whole batch"}
    return outcome.op("success" if ok else "partial", ok, {"steps_done": len(results)}, results=results,
                      not_run=not_run, snapshot=snapshot, **why)


HANDLERS = {"doctor": diagnostics.doctor, "timeline_summary": inspection.timeline_summary,
            "inspect_range": inspection.inspect_range, "find_media": inspection.find_media,
            "snapshot_timeline": timeline.snapshot_timeline, "place_clips": placement.place_clips,
            "move_item": replace.move_item, "trim_item": replace.trim_item, "ripple_trim": ripple.ripple_trim,
            "set_enabled": clips.set_enabled, "set_fades": clips.set_fades, "add_transition": clips.add_transition,
            "set_audio": audio.set_audio, "normalize_audio": audio.normalize_audio, "set_speed": clips.set_speed,
            "copy_grade": clips.copy_grade, "add_markers": markers.add_markers,
            "add_audio_markers": markers.add_audio_markers, "add_captions": captions.add_captions,
            "export_srt": captions.export_srt, "export_timeline": delivery.export_timeline,
            "qc_file": delivery.qc_file, "batch": batch, "audit_log": diagnostics.audit_log}
READ_ONLY = {"doctor", "timeline_summary", "inspect_range", "find_media", "audit_log", "qc_file"}
# Tools that change nothing until confirm=true. A batch preview calls only these, so add a tool here only if that holds.
PREVIEWABLE = {"place_clips", "move_item", "trim_item", "ripple_trim", "normalize_audio", "set_speed", "copy_grade",
               "add_captions"}
# Tools that take confirm=true. Their previews name the timeline, and a confirm must name it too (ISSUES.md I-17).
CONFIRMABLE = PREVIEWABLE | {"batch"}
# Reads that may follow a switch by hand, so they check the current timeline before using cached reads.
TIMELINE_READS = {"timeline_summary", "inspect_range", "find_media"}


def run(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Entry point of every edit__ tool. Resolve acts on the current timeline, so a call that writes is pinned to
    the one that was current when it started, batch steps included (ISSUES.md I-16)."""
    if "confirm" in args:
        args = {**args, "confirm": args["confirm"] is True}  # "false", "no" and 1 are truthy but are not approval
    if session.pin is None and name in TIMELINE_READS:
        session.drop_if_switched()
    if session.pin is None and name not in READ_ONLY:
        session.invalidate()  # the user may have switched since the last read
        if _writes(name, args):
            return _run_pinned(name, args)
    result = _dispatch(name, args)
    if session.pin is None and name in CONFIRMABLE and result.get("_operation", {}).get("status") == "preview":
        result["timeline"] = session.get_state()["timeline"]  # the confirm must name it
    return result


def _writes(name: str, args: dict[str, Any]) -> bool:
    if name == "export_srt" or (args.get("dry_run") and name in ("add_audio_markers", "add_captions")):
        return False  # no Resolve timeline involved, or nothing written to it
    return bool(args.get("confirm")) or (name not in PREVIEWABLE and name != "batch")


def _run_pinned(name: str, args: dict[str, Any]) -> dict[str, Any]:
    state = session.get_state()
    if not state.get("timeline"):
        return outcome.blocked("no current timeline")
    if not state.get("pins"):
        return outcome.blocked("the Resolve bridge is older than this server and can't hold an edit on one timeline; "
                               "restart the bridge (Workspace > Scripts > resolve_bridge)")
    if name in CONFIRMABLE and args.get("confirm") is True:
        given, current = args.get("timeline"), state["timeline"]
        if not given:
            return outcome.blocked(f"confirm=true needs timeline=<name> from the preview (now current: {current}); "
                                   "preview again if you don't have it")
        if given != current:
            return outcome.blocked(f"the preview was for {given}, but {current} is current now; nothing was changed. "
                                   "Switch back to it or preview again")
    session.pin = {"project": state.get("project"), "name": state["timeline"]}
    session.switched.clear()
    warnings = []
    try:
        result = _dispatch(name, args)
    finally:
        try:
            session.call("get_state")  # pinned, so this also takes Resolve back to the timeline
        except Exception as exc:  # must not hide the tool's own result or error
            warnings.append(f"could not return to {session.pin['name']}: {exc}")
        target, session.pin = session.pin["name"], None
    warnings += [f"Resolve had switched to {other}; switched back to {target}" for other in sorted(session.switched)]
    if warnings:
        result.setdefault("_operation", {}).setdefault("warnings", []).extend(warnings)
    return result


def _dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    result = HANDLERS[name](args)
    status = result.get("_operation", {}).get("status") if isinstance(result, dict) else None
    if name not in READ_ONLY and status not in (None, "preview", "planned", "blocked"):
        session.invalidate()
        audit.log_audit("edit__" + name, args, status)
    return result
