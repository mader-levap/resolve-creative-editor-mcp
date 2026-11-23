"""Tool definitions of the edit__ tools."""
from .common import B, I, N, S, T

IDS = {"type": "array", "items": S}
WHEN = {"type": ["integer", "string"], "description": "Absolute timeline frame or timecode like 01:00:12:05"}
CONFIRM = {"type": "boolean", "description": "Omit for a preview. Set true only after the user approves."}
TIMELINE = {"type": "string", "description": "With confirm=true: the timeline named in the preview. The edit is "
            "refused if another timeline is current."}
SEGMENTS = {"type": "array", "items": {"type": "object", "properties": {"start": N, "end": N, "text": S},
                                       "required": ["start", "end", "text"]},
            "description": "Caption lines in seconds. Omit to transcribe `path` instead."}
TOOLS = [
    T("doctor", "Check Python, FFmpeg, transcription, the upstream engine and the live Resolve bridge."),
    T("timeline_summary", "Compact health check of the current timeline: per-track counts, gaps, overlaps, "
      "transitions and reused source clips, with timecodes. Run before editing. limit caps listed issues.",
      {"limit": I}),
    T("inspect_range", "Items between two points (frames or timecodes). details=true adds grade, transform, "
      "fades, speed and markers per item.", {"start": WHEN, "end": WHEN, "details": B}, ["start", "end"]),
    T("find_media", "Search the media pool by name. Returns id, name, frames, fps.", {"query": S, "limit": I}),
    T("snapshot_timeline", "Duplicate the current timeline as a timestamped backup and stay on the original.",
      {"label": S}),
    T("place_clips", "Put media-pool clips on the timeline at exact frames. Source range is [start_frame, end_frame) "
      "in the clip's own frames. Refuses anything that would overwrite existing items.",
      {"clips": {"type": "array", "items": {"type": "object", "properties": {
          "clip": S, "start_frame": I, "end_frame": I, "record": WHEN, "track_index": I,
          "media_type": {"type": "integer", "enum": [1, 2], "description": "1 video only, 2 audio only"}},
          "required": ["clip", "record"]}}, "confirm": CONFIRM, "timeline": TIMELINE}, ["clips"]),
    T("move_item", "Move a clip (and its linked audio/video) to a new frame or track. Builds the replacement first and "
      "copies grade, transform, audio levels, fades, colour, flags and markers onto it. Keyframes are not copied.",
      {"item_id": S, "record": WHEN, "track_index": I, "include_linked": B, "confirm": CONFIRM, "timeline": TIMELINE},
      ["item_id", "record"]),
    T("trim_item", "Trim a clip (and its linked audio/video). Positive frames shorten that end, negative extend it "
      "into spare source media. Same settings-preserving method as move_item.",
      {"item_id": S, "head_frames": I, "tail_frames": I, "include_linked": B, "confirm": CONFIRM, "timeline": TIMELINE},
      ["item_id"]),
    T("ripple_trim", "Shorten clips' ends by tail_frames and pull everything after them earlier on all tracks, so the "
      "gaps stay the same. Works on Text+ titles and generators: nothing is rebuilt, so text, style, fades and "
      "keyframes stay. Video items without linked audio only.",
      {"item_ids": IDS, "tail_frames": I, "confirm": CONFIRM, "timeline": TIMELINE}, ["item_ids", "tail_frames"]),
    T("set_enabled", "Disable or enable clips: a reversible alternative to deleting them.",
      {"item_ids": IDS, "enabled": B}, ["item_ids", "enabled"]),
    T("set_fades", "Set video or audio fade-in/out lengths in frames on clips, with read-back. An end you leave out "
      "keeps its current length. Resolve bug: fades are only saved on clips where the user has dragged a fade "
      "handle by hand at least once; otherwise they are lost on restart.",
      {"item_ids": IDS, "fade_in": I, "fade_out": I}, ["item_ids"]),
    T("add_transition", "Add a native transition at the start or end of a clip (Resolve 21.1+). Needs spare source "
      "frames on both sides of the cut. Previews first (cut, expected span, spare source frames); confirm makes a "
      "backup timeline, adds it and checks what Resolve made. On a video clip, linked audio at the same cut gets a "
      "matching crossfade (audio_type, default 'Cross Fade +3 dB') unless include_linked is false.",
      {"item_id": S, "type": S, "position": {"type": "string", "enum": ["start", "end"]},
       "alignment": {"type": "string", "enum": ["left", "center", "right"]},
       "duration": {"type": "integer", "minimum": 1, "description": "Frames; leave out for Resolve's default"},
       "category": {"type": "string", "enum": ["simple", "fusion", "ofx", "audio"]}, "include_linked": B,
       "audio_type": S, "confirm": CONFIRM,
       "timeline": TIMELINE}, ["item_id"]),
    T("set_audio", "Set clip volume (dB) and/or pan (-100..100) on audio items, with read-back.",
      {"item_ids": IDS, "volume_db": N, "pan": N}, ["item_ids"]),
    T("normalize_audio", "Normalize audio clips with Resolve's own loudness modes (e.g. 'EBU R128', 'YouTube').",
      {"item_ids": IDS, "mode": S, "target_level": N, "target_loudness": N,
       "independent": {"type": "boolean", "description": "Level each clip separately instead of keeping balance"},
       "confirm": CONFIRM, "timeline": TIMELINE}, ["item_ids"]),
    T("set_speed", "Change clip speed (percentage, 0 = freeze). Doesn't ripple the timeline.",
      {"item_id": S, "percentage": N, "confirm": CONFIRM, "timeline": TIMELINE}, ["item_id", "percentage"]),
    T("copy_grade", "Copy one clip's grade onto other clips.",
      {"from_id": S, "to_ids": IDS, "confirm": CONFIRM, "timeline": TIMELINE}, ["from_id", "to_ids"]),
    T("add_markers", "Add several timeline markers at once, read back. Every marker needs a name: Resolve 21.2 "
      "refuses markers without one.",
      {"markers": {"type": "array", "items": {"type": "object", "properties": {
          "at": WHEN, "name": S, "note": S, "color": S, "duration": I}, "required": ["at", "name"]}}}, ["markers"]),
    T("add_audio_markers", "Mark silences or musical onsets found in a file. dry_run only lists them. Measurements, "
      "not edit decisions. timeline_offset_frames is where the file starts relative to the timeline start.",
      {"path": S, "kind": {"type": "string", "enum": ["silence", "beats"]}, "timeline_offset_frames": I,
       "color": S, "noise_db": N, "min_duration": N, "max_markers": I, "dry_run": B}, ["path", "kind"]),
    T("add_captions", "Editable Text+ captions at exact times and lengths, from segments or by transcribing `path`. "
      "record is where the audio starts (default timeline start). Each caption is a small timeline in a bin, "
      "placed like a clip; long lines are split. dry_run only lists them.",
      {"path": S, "segments": SEGMENTS, "record": WHEN, "track_index": I, "max_chars": I, "model": S, "language": S,
       "font": S, "size": N, "y": N, "dry_run": B, "confirm": CONFIRM, "timeline": TIMELINE}),
    T("export_srt", "Write an .srt subtitle file from segments or by transcribing `path`. Import it in Resolve with "
      "File > Import > Subtitle (importing subtitles by script can crash Resolve 21).",
      {"path": S, "segments": SEGMENTS, "output": S, "model": S, "language": S, "max_chars": I}),
    T("export_timeline", "Export the current timeline as OTIO, FCPXML, EDL, AAF or DRT for review or hand-off.",
      {"format": {"type": "string", "enum": ["OTIO", "FCPXML", "EDL", "AAF", "DRT"]}, "output": S}, ["format"]),
    T("qc_file", "Quality check a rendered file: loudness (LUFS, true peak), black frames, frozen frames, silence.",
      {"path": S}, ["path"]),
    T("batch", "Run several edit__ tools in order with one backup, stopping at the first step that isn't a success "
      "(partial included): the result says why and lists not_run. Each operation is "
      "{tool, args}. Without confirm=true nothing is changed: steps that have a preview show it, the others are only "
      "listed. confirm applies to all of them; confirm inside a step's args is ignored.",
      {"operations": {"type": "array",
                      "items": {"type": "object", "properties": {"tool": S, "args": {"type": "object"}},
                                "required": ["tool"]}},
       "confirm": CONFIRM, "timeline": TIMELINE}, ["operations"]),
    T("audit_log", "Recent changes made through this server.", {"limit": I}),
]
NAMES = {t["name"] for t in TOOLS}
