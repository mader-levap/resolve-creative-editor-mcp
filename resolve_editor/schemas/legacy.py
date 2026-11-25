"""Tool definitions of the legacy server: one per bridge operation, then the media tools."""
from . import media
from .common import B, I, S, T

STRS = {"type": "array", "items": S}
CLIP_REF = "clip id (preferred) or exact name"

TOOLS = [
    T("get_state", "Resolve version, current page/project/timeline, fps, frame range, playhead timecode."),
    T("list_timelines", "Names of all timelines in the current project."),
    T("set_current_timeline", "Switch the active timeline.", {"name": S}, ["name"]),
    T("list_media", "All clips in the media pool (id, name, duration, frames, fps, resolution, path)."),
    T("import_media", "Import files from disk into the media pool.", {"paths": STRS}, ["paths"]),
    T("create_bin", "Create a Media Pool bin by its path from the root, / between levels (e.g. Footage/Day 1). Only "
      "the last level is created; its parent must exist. The current bin doesn't change.", {"bin": S}, ["bin"]),
    T("use_bin", "Make a bin current (path from the root; empty is the root). New clips and timelines go there. "
      "Returns the previous bin, to switch back to it later.", {"bin": S}, ["bin"]),
    T("delete_bin", "Delete a bin (path from the root). A bin with clips, timelines or bins in it is refused unless "
      "with_contents=true, which deletes them with it (Media Pool entries only, files on disk stay). Refuses the "
      "root, the current bin and a bin holding the current timeline.", {"bin": S, "with_contents": B}, ["bin"]),
    T("delete_timeline", "Delete timelines by exact name (Media Pool entries only). Refuses the current timeline and "
      "unknown names before deleting anything. with_captions=true also deletes the caption timelines placed on them "
      "(edit__add_captions), except ones a remaining timeline still uses, which are kept and named.",
      {"names": STRS, "with_captions": B}, ["names"]),
    T("create_timeline", "Create a timeline, empty or from media-pool clips.",
      {"name": S, "clips": {"type": "array", "items": S, "description": CLIP_REF}}, ["name"]),
    T("append_clips",
      "Append clips to the current timeline. Use start_frame/end_frame as a half-open source range "
      "[start_frame, end_frame): end_frame is exclusive. Duration is end-start. To cut a "
      "sub-range; this is the way to trim/cut. record_frame places it at a timeline position.",
      {"clips": {"type": "array", "items": {"type": "object", "properties": {
          "clip": S, "start_frame": I, "end_frame": I, "track_index": I, "record_frame": I,
          "media_type": {"type": "integer", "enum": [1, 2], "description": "1=video only, 2=audio only"}},
          "required": ["clip"]}}}, ["clips"]),
    T("add_track", "Add a track (audio is stereo) to the current timeline.",
      {"track_type": {"type": "string", "enum": ["audio", "video"]}}),
    T("duplicate_timeline", "Duplicate the current timeline under a new name.", {"name": S}, ["name"]),
    T("set_grade", "Primary colour grade (ASC CDL on a node, default 1) for timeline items. slope/offset/power are "
      "'r g b' strings, e.g. slope '1.05 1.0 0.95' warms; saturation e.g. 1.15. No values = reset to neutral.",
      {"item_ids": STRS, "slope": S, "offset": S, "power": S, "saturation": {"type": "number"}, "node": I},
      ["item_ids"]),
    T("probe_color", "Report which colour-page calls Resolve exposes for a timeline item (changes nothing).",
      {"item_id": S}, ["item_id"]),
    T("refresh_luts", "Make Resolve rescan its LUT folders."),
    T("set_lut", "Load a .cube LUT onto a node (default 1) of timeline items.",
      {"item_ids": STRS, "path": S, "node": I}, ["item_ids", "path"]),
    T("list_timeline_items", "Items on the current timeline's tracks.",
      {"track_type": {"type": "string", "enum": ["video", "audio", "subtitle"]}}),
    T("set_item_properties",
      "Set transform/composite props on a timeline item (Pan, Tilt, ZoomX, ZoomY, Opacity, RotationAngle, "
      "Crop*, FlipX/Y, ...).", {"item_id": S, "properties": {"type": "object"}}, ["item_id", "properties"]),
    T("delete_items", "Delete timeline items.", {"item_ids": STRS, "ripple": B}, ["item_ids"]),
    T("add_text_plus", "Insert editable Text+ titles at timeline frames, set their text and optional style. "
      "lock_video_tracks keeps titles off those tracks while inserting.",
      {"items": {"type": "array", "items": {"type": "object", "properties": {"text": S, "record_frame": I, "frames": I},
                                            "required": ["text", "record_frame"]}},
       "font": S, "style": S, "size": {"type": "number"}, "x": {"type": "number"}, "y": {"type": "number"},
       "lock_video_tracks": {"type": "array", "items": I},
       "inputs": {"type": "object", "description": "other Text+ inputs by id: a number, a string or [x, y]"},
       "list_inputs": B}, ["items"]),
    T("style_text_plus", "Change existing Text+ titles or captions in place: text, font, style, size, x, y, other "
      "Text+ inputs by id (number, string or [x, y]). text replaces the whole text of every listed title; use \\n "
      "for line breaks.",
      {"item_ids": STRS, "text": S, "font": S, "style": S, "size": {"type": "number"}, "x": {"type": "number"},
       "y": {"type": "number"}, "inputs": {"type": "object"}}, ["item_ids"]),
    T("add_marker", "Add a timeline marker. frame is relative to the timeline start. Colors: Blue, Cyan, Green, "
      "Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream. name is required: "
      "Resolve 21.2 refuses markers without one.",
      {"frame": I, "color": S, "name": S, "note": S, "duration": I}, ["frame", "name"]),
    T("list_markers", "All timeline markers keyed by frame."),
    T("delete_marker", "Delete the marker at a frame.", {"frame": I}, ["frame"]),
    T("goto_timecode", "Move the playhead, e.g. 01:00:05:00.", {"timecode": S}, ["timecode"]),
    T("export_frame", "Return the frame at a timecode (or the playhead) as an image so you can SEE the result.",
      {"timecode": S}),
    T("open_page", "Switch Resolve page.",
      {"page": {"type": "string", "enum": ["media", "cut", "edit", "fusion", "color", "fairlight", "deliver"]}},
      ["page"]),
    T("save_project", "Save the current project."),
    T("list_render_presets", "Available render presets."),
    T("queue_render", "Queue the current timeline for render (does not start it).",
      {"target_dir": S, "name": S, "preset": S}, ["target_dir", "name"]),
    T("start_render", "Start rendering queued jobs (all, or the given job ids).", {"job_ids": STRS}),
    T("render_status", "Render progress and per-job status."),
] + media.TOOLS
