"""Timeline export and checks of rendered files."""
import os
import re
from typing import Any

from .. import media, outcome, paths, session


def export_timeline(args: dict[str, Any]) -> dict[str, Any]:
    """edit__export_timeline: export the current timeline (OTIO, FCPXML, EDL, AAF, DRT) to a new file."""
    suffix = {"OTIO": ".otio", "FCPXML": ".fcpxml", "EDL": ".edl", "AAF": ".aaf", "DRT": ".drt"}[args["format"]]
    output = paths.new_output(args, suffix)
    ok = session.call("export_timeline", path=output, format=args["format"]).get("ok") and os.path.exists(output)
    return outcome.op("success" if ok else "failed", ok, {"file_written": output if ok else None})


def parse_qc(log: str) -> dict[str, Any]:
    """Read FFmpeg's text log of the QC filters: the last loudness values reported, and at most 20 of each
    kind of black, frozen and silent segment."""
    def last(pattern: str) -> float | None:
        hits = re.findall(pattern, log)
        return float(hits[-1]) if hits else None
    black = [[float(a), float(b)] for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]
    freeze = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    silence = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    return {"integrated_lufs": last(r"I:\s+(-?[\d.]+) LUFS"), "loudness_range_lu": last(r"LRA:\s+([\d.]+) LU"),
            "true_peak_dbfs": last(r"Peak:\s+(-?[\d.]+) dBFS"), "black_segments": black[:20],
            "frozen_at_seconds": freeze[:20], "silence_at_seconds": silence[:20]}


def qc_file(args: dict[str, Any]) -> dict[str, Any]:
    """edit__qc_file: loudness, true peak, and black, frozen and silent parts of a rendered file, via FFmpeg."""
    ffmpeg = media.binary("ffmpeg", "FFMPEG")
    proc = media.run_command([ffmpeg, "-nostdin", "-hide_banner", "-i", media.media_path(args["path"]),
                              "-vf", "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-60dB:d=2",
                              "-af", "ebur128=peak=true,silencedetect=n=-50dB:d=1", "-f", "null", "-"], 3600)
    report = parse_qc(proc.stderr)
    notes = []
    if report["true_peak_dbfs"] is not None and report["true_peak_dbfs"] > -1:
        notes.append("true peak above -1 dBFS may clip after upload encoding")
    if report["integrated_lufs"] is not None and not -16 <= report["integrated_lufs"] <= -12:
        notes.append("YouTube-style targets are around -14 LUFS")
    return outcome.op("success", True, warnings=notes, qc=report)
