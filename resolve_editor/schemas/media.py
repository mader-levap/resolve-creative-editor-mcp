"""Tool definitions of the local media tools."""
from .common import I, S, T

TOOLS = [
    T("probe_media", "Inspect a media file with ffprobe: duration, codecs, resolution, frame rate, audio streams.",
      {"path": S}, ["path"]),
    T("extract_audio", "Extract the first audio stream to a 48 kHz stereo WAV for auditioning or external analysis.",
      {"path": S, "sample_rate": I}, ["path"]),
    T("detect_silence", "Detect silence intervals in an audio/video file using FFmpeg. Thresholds are configurable.",
      {"path": S, "noise_db": {"type": "number"}, "min_duration": {"type": "number"}}, ["path"]),
    T("transcribe_audio", "Optional local transcription using faster-whisper. Install faster-whisper separately; no model is downloaded automatically.",
      {"path": S, "model": {"type": "string", "enum": ["tiny", "base", "small"]},
       "language": S}, ["path"]),
    T("make_contact_sheet", "Create a visual contact sheet from a video so the editor can review many shots at once.",
      {"path": S, "interval_seconds": {"type": "number"}, "columns": I}, ["path"]),
]
