"""Timeline markers, also from silences and onsets found in audio."""
import array
import math
import statistics
import subprocess

from .. import media, outcome, session, timecode


def add_markers(a):
    _, _, state = session.clock()
    start = state["timeline_start_frame"]
    markers = [{"frame": session.to_frame(m["at"]) - start, "name": m.get("name") or "", "note": m.get("note") or "",
                "color": m.get("color") or "Blue", "duration": m.get("duration") or 1} for m in a["markers"]]
    added = session.call("add_markers", markers=markers).get("added", 0)
    return outcome.op("success" if added == len(markers) else "partial", added == len(markers),
                      {"markers_added": added},
                      [] if added == len(markers) else ["a marker already exists at some of those frames"])


def onsets(samples, rate, hop=512, min_gap=0.25):
    """Energy-flux onset times in seconds. Works best on percussive audio."""
    energy = []
    for i in range(0, len(samples) - hop, hop):
        chunk = samples[i:i + hop]
        energy.append(math.log(sum(x * x for x in chunk) / hop + 1e-4))  # floor about -40 dB ignores hiss
    flux = [max(0.0, b - a) for a, b in zip(energy, energy[1:], strict=False)]
    if len(flux) < 8:
        return []
    window, last, out = max(8, int(rate / hop)), -min_gap, []
    for i, value in enumerate(flux):
        local = flux[max(0, i - window):i + window]
        t = (i + 1) * hop / rate
        if value > statistics.mean(local) + 1.5 * statistics.pstdev(local) and value > 0.5 and t - last >= min_gap:
            out.append(round(t, 3))
            last = t
    return out


def _beats(path):
    rate = 11025
    ffmpeg = media.binary("ffmpeg", "FFMPEG")
    proc = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", media.media_path(path), "-map", "0:a:0", "-ac", "1",
                           "-ar", str(rate), "-f", "s16le", "-"], capture_output=True, timeout=600)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-2000:])
    samples = array.array("h")
    samples.frombytes(proc.stdout[:len(proc.stdout) // 2 * 2])
    return onsets([x / 32768 for x in samples], rate)


def add_audio_markers(a):
    if a["kind"] == "beats":
        found = [{"start": t, "end": t} for t in _beats(a["path"])]
        name, color = "beat", a.get("color") or "Cyan"
    else:
        args = {"path": a["path"]}
        args.update({k: a[k] for k in ("noise_db", "min_duration") if k in a})
        result = media.run_media_tool("detect_silence", args)
        length = float(media.run_media_tool("probe_media", {"path": a["path"]}).get("duration") or 0)
        found = [{"start": x["start"], "end": x["end"] if x["end"] is not None else length}
                 for x in result["silence_intervals"]]
        name, color = "silence", a.get("color") or "Yellow"
    limit = a.get("max_markers") or 200
    warnings = [f"found {len(found)}, kept the first {limit}"] if len(found) > limit else []
    found = found[:limit]
    if a.get("dry_run"):
        return outcome.op("planned", times=[[x["start"], x["end"]] for x in found], warnings=warnings)
    fps, _, _ = session.clock()
    offset = a.get("timeline_offset_frames") or 0
    markers = [{"frame": offset + timecode.seconds_to_frames(x["start"], fps), "name": name, "color": color,
                "duration": max(1, timecode.seconds_to_frames(x["end"] - x["start"], fps))} for x in found]
    added = session.call("add_markers", markers=markers).get("added", 0) if markers else 0
    return outcome.op("success" if added == len(markers) else "partial", added == len(markers),
                      {"markers_added": added}, warnings)
