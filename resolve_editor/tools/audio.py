"""Clip volume, pan and normalization."""
from typing import Any

from .. import outcome, session


def set_audio(args: dict[str, Any]) -> dict[str, Any]:
    """edit__set_audio: set clip volume (dB) and/or pan and read them back; partial if an item didn't take them."""
    props = {}
    if args.get("volume_db") is not None:
        props["AudioVolume"] = float(args["volume_db"])
    if args.get("pan") is not None:
        props["AudioPan"] = float(args["pan"])
    if not props:
        return outcome.blocked("give volume_db and/or pan")
    ok_count = 0
    for i in args["item_ids"]:
        session.call("set_item_properties", item_id=i, properties=props)
    for d in session.as_list(session.call("item_details", item_ids=args["item_ids"])):
        got = d.get("properties") or {}
        ok_count += all(abs(float(got.get(k, 1e9)) - v) < 0.01 for k, v in props.items())
    ok = ok_count == len(args["item_ids"])
    return outcome.op("success" if ok else "partial", ok, {"items_changed": ok_count},
                      [] if ok else ["some items are not audio, or Resolve clamped the value"])


def normalize_audio(args: dict[str, Any]) -> dict[str, Any]:
    """edit__normalize_audio: preview, then normalize with one of Resolve's loudness modes; the gain can't
    be verified by script."""
    modes = [v for k, v in (session.call("audio_modes") or {}).items() if k != "__flags"]
    mode = args.get("mode") or "EBU R128"
    if mode not in modes:
        return outcome.blocked(f"unknown mode {mode!r}; choose from {modes}")
    options = {"normalizationMode": mode,
               "setLevelMode": "NORMALIZE_AUDIO_SET_LEVEL_INDEPENDENT" if args.get("independent")
               else "NORMALIZE_AUDIO_SET_LEVEL_RELATIVE"}
    if args.get("target_level") is not None:
        options["targetLevel"] = args["target_level"]
    if args.get("target_loudness") is not None:
        options["targetLoudness"] = args["target_loudness"]
    if not args.get("confirm"):
        return outcome.preview({"items": len(args["item_ids"]), "options": options},
                               ["changes clip gain; Ctrl+Z in Resolve undoes it"])
    before = {d["id"]: (d.get("properties") or {}).get("AudioVolume")
              for d in session.as_list(session.call("item_details", item_ids=args["item_ids"]))}
    ok = session.call("normalize_audio", item_ids=args["item_ids"], options=options).get("ok")
    after = {d["id"]: (d.get("properties") or {}).get("AudioVolume")
             for d in session.as_list(session.call("item_details", item_ids=args["item_ids"]))}
    return outcome.op("success" if ok else "failed", None,
                      {"gain_db": {i: [before.get(i), after.get(i)] for i in after}},
                      ["clip-volume read-back may not reflect normalization gain; listen to confirm"])
