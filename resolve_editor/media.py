"""Local media analysis with FFmpeg and faster-whisper. Source files are only read."""
import base64
import json
import os
import re
import shutil
import subprocess
from typing import Any

from . import paths


def media_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("path must be a non-empty string")
    path = os.path.abspath(os.path.expanduser(value))
    if not os.path.isfile(path):
        raise FileNotFoundError(f"media file not found: {path}")
    return path


def binary(name: str, env_name: str) -> str:
    candidate = os.environ.get(env_name) or shutil.which(name)
    if not candidate:
        raise RuntimeError(f"{name} was not found. Install FFmpeg and ensure {name} is on PATH, or set {env_name}.")
    return candidate


def _run_media_command(cmd: list[str], timeout: float = 300) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown FFmpeg error")[-4000:]
        raise RuntimeError(detail)
    return proc


def _probe_media(source: str, args: dict[str, Any]) -> dict[str, Any]:
    ffprobe = binary("ffprobe", "FFPROBE")
    proc = _run_media_command([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", source], 60)
    info = json.loads(proc.stdout)
    fmt = info.get("format", {})
    streams = []
    for stream in info.get("streams", []):
        streams.append({
            "index": stream.get("index"), "type": stream.get("codec_type"),
            "codec": stream.get("codec_name"), "duration": stream.get("duration"),
            "sample_rate": stream.get("sample_rate"), "channels": stream.get("channels"),
            "width": stream.get("width"), "height": stream.get("height"),
            "frame_rate": stream.get("avg_frame_rate") or stream.get("r_frame_rate"),
            "pixel_format": stream.get("pix_fmt")
        })
    return {"path": source, "duration": fmt.get("duration"), "format": fmt.get("format_name"),
            "bit_rate": fmt.get("bit_rate"), "streams": streams}


def _extract_audio(source: str, args: dict[str, Any]) -> dict[str, Any]:
    ffmpeg = binary("ffmpeg", "FFMPEG")
    rate = int(args.get("sample_rate") or 48000)
    if rate not in (16000, 24000, 44100, 48000):
        raise ValueError("sample_rate must be 16000, 24000, 44100 or 48000")
    output = paths.media_output(source, ".wav")
    _run_media_command([ffmpeg, "-nostdin", "-y", "-i", source, "-map", "0:a:0",
                        "-vn", "-ac", "2", "-ar", str(rate), "-c:a", "pcm_s16le", output], 600)
    return {"source": source, "audio_path": output, "sample_rate": rate, "channels": 2,
            "note": "This is an extracted, playable WAV file; it has not been subjectively auditioned."}


def _detect_silence(source: str, args: dict[str, Any]) -> dict[str, Any]:
    ffmpeg = binary("ffmpeg", "FFMPEG")
    noise = float(args.get("noise_db", -35))
    duration = float(args.get("min_duration", 0.35))
    if not -90 <= noise <= 0 or not 0.05 <= duration <= 10:
        raise ValueError("noise_db must be -90..0 and min_duration must be 0.05..10 seconds")
    proc = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-i", source,
                           "-af", f"silencedetect=noise={noise}dB:d={duration}", "-f", "null", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "FFmpeg silence detection failed")[-4000:])
    log = proc.stderr or ""
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", log)]
    intervals = []
    for i, start in enumerate(starts):
        intervals.append({"start": start, "end": ends[i] if i < len(ends) else None})
    return {"path": source, "noise_threshold_db": noise, "minimum_duration": duration,
            "silence_intervals": intervals,
            "warning": "Silence detection is signal analysis, not a judgement that a pause should be cut."}


def _transcribe_audio(source: str, args: dict[str, Any]) -> dict[str, Any]:
    import hashlib
    model_size = args.get("model") or "base"
    language = args.get("language") or ""
    digest = hashlib.sha256()
    with open(source, "rb") as media_file:
        for chunk in iter(lambda: media_file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    cache_key = hashlib.sha256(f"{digest.hexdigest()}|{model_size}|{language}".encode("utf-8")).hexdigest()
    cache_dir = os.path.join(paths.DIR, "transcripts")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, cache_key + ".json")
    if os.path.isfile(cache_path):
        with open(cache_path, "r", encoding="utf-8") as cached_file:
            cached = json.load(cached_file)
        cached["cache_hit"] = True
        cached["note"] = "Cached draft transcription; listen to recordings before making dialogue cuts."
        return cached
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Optional dependency missing: install faster-whisper with "
                           "`pip install faster-whisper`.") from exc
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, meta = model.transcribe(source, language=language or None, word_timestamps=True, vad_filter=True)
    result = []
    for seg in segments:
        result.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text,
                       "words": [{"start": round(w.start, 3) if w.start is not None else None,
                                  "end": round(w.end, 3) if w.end is not None else None,
                                  "word": w.word, "probability": w.probability} for w in (seg.words or [])]})
    payload = {"path": source, "source_sha256": digest.hexdigest(), "model": model_size,
               "language": meta.language, "language_probability": meta.language_probability,
               "segments": result, "cache_hit": False,
               "note": "Transcription is a draft; listen to recordings before making dialogue cuts."}
    temp_path = cache_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=False)
    os.replace(temp_path, cache_path)
    return payload


def _make_contact_sheet(source: str, args: dict[str, Any]) -> dict[str, Any]:
    ffmpeg = binary("ffmpeg", "FFMPEG")
    interval = float(args.get("interval_seconds") or 3)
    columns = int(args.get("columns") or 4)
    if not 0.5 <= interval <= 60 or not 1 <= columns <= 8:
        raise ValueError("interval_seconds must be 0.5..60 and columns must be 1..8")
    output = paths.media_output(source, ".jpg")
    vf = f"fps=1/{interval},scale=320:-1,tile={columns}x4"
    _run_media_command([ffmpeg, "-nostdin", "-y", "-i", source, "-vf", vf,
                        "-frames:v", "1", "-q:v", "3", output], 600)
    with open(output, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return {"path": output, "image": encoded, "mimeType": "image/jpeg",
            "note": "Contact sheet is a visual sampling; inspect source footage before final shot decisions."}


HANDLERS = {"probe_media": _probe_media, "extract_audio": _extract_audio, "detect_silence": _detect_silence,
            "transcribe_audio": _transcribe_audio, "make_contact_sheet": _make_contact_sheet}


def run_media_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    source = media_path(args.get("path"))
    if name not in HANDLERS:
        raise ValueError(f"unsupported media tool: {name}")
    return HANDLERS[name](source, args)
