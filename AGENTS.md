# DaVinci Resolve for AI agents

## Working rules

- Prefer `edit__`; use `legacy__` only for what `edit__` can't do.
- Start with `edit__timeline_summary`, then `edit__inspect_range` for just the part you will change. Don't list whole timelines repeatedly. Reads are cached for a few seconds; writes clear the cache.
- Show previews to the user before confirming. Some writing tools have no preview and run on the first call.
- Group several changes with `edit__batch`.
- Prefer `edit__set_enabled` (reversible) over deleting clips.
- Use explicit project and timeline names, and check which timeline is current before writing.

## Editing workflow

1. Inspect Resolve version, project, timeline, frame rate and media.
2. Check existing analysis and transcripts before repeating work, then analyze the footage.
3. Plan the edit with source-frame ranges and reasons.
4. Show the cut list and major editorial choices before destructive changes.
5. Back up the timeline.
6. Edit in small batches, read back, and compare expected with actual.
7. Inspect rendered frames at representative cuts.
8. Review dialogue continuity, room tone, music balance, titles and captions. Ask the user to judge what must be heard.
9. Run final deliverable checks. A successful API response alone doesn't mean the work is done.

## Creative priorities

In order: story/emotion, clarity, rhythm, continuity, visual polish.

- Don't cut a pause just because it is quiet. Keep breaths, comic timing, reactions and meaningful silence.
- Don't pick a take from transcript text alone when delivery, emotion or audio quality matters.
- Don't pick music from metadata or beat analysis alone. Have the user audition it against the picture.

## Media and performance

- Source media is read-only. Never overwrite originals; write derivatives to analysis or scratch locations.
- Don't install heavyweight local models unless the user asks.
- Transcribe with CPU/int8 and small/base models unless the user chooses otherwise. Transcripts are cached by content hash, so don't work around the cache.
- On Studio, keep the compound upstream server (37 tools). Use the granular one (390 tools) only for a specific missing API.

## Available tools

All tools come from the `resolve-creative-editor` MCP server (61 on free Resolve; `resolve__` timeline tools need Studio and are hidden). `edit__` tools that take `confirm` return a preview first; repeat with `confirm=true`. The others run on the first call.

### `edit__`: checked editing (preferred)

- **edit__doctor**: check Python, FFmpeg, transcription, the upstream engine and the live Resolve bridge.
- **edit__timeline_summary**: per-track counts, gaps, overlaps, transitions and reused clips. Run before editing.
- **edit__inspect_range**: items between two frames/timecodes; `details` adds grade, transform, fades, speed, markers.
- **edit__find_media**: search the Media Pool by name (id, name, frames, fps, type).
- **edit__snapshot_timeline**: duplicate the current timeline as a timestamped backup and stay on the original.
- **edit__place_clips**: put Media Pool clips at exact frames and tracks; refuses to overwrite.
- **edit__move_item**: move a clip (and linked audio/video) by rebuilding it with its settings; not titles.
- **edit__trim_item**: trim either end of a clip by rebuilding it with its settings; not titles.
- **edit__ripple_trim**: shorten clip ends in place and pull everything after them earlier; works on titles.
- **edit__set_enabled**: disable/enable clips (reversible alternative to deleting).
- **edit__set_fades**: video/audio fade-in/out in frames, with read-back. Only saved on clips with a hand-dragged fade (Resolve bug, see Editing below).
- **edit__add_transition**: native transition at a clip's start or end (Resolve 21.1+).
- **edit__set_audio**: clip volume (dB) and pan, with read-back.
- **edit__normalize_audio**: normalize clips with Resolve's loudness modes (EBU R128, YouTube, ...).
- **edit__set_speed**: change clip speed (0 = freeze); doesn't ripple.
- **edit__copy_grade**: copy one clip's grade onto other clips.
- **edit__add_markers**: add several timeline markers at once.
- **edit__add_audio_markers**: mark silences or beats found in a file.
- **edit__add_captions**: editable Text+ captions at exact times, from segments or by transcribing a file.
- **edit__export_srt**: write an .srt from segments or a transcription (user imports it by hand).
- **edit__export_timeline**: export the current timeline as OTIO, FCPXML, EDL, AAF or DRT.
- **edit__qc_file**: QC a rendered file: loudness, true peak, black/frozen frames, silence.
- **edit__batch**: run several `edit__` tools with one backup. It stops after any step that isn't a success (`partial` too) and says why and what didn't run: read back, then run only what is left. An error still loses the results and backup name (ISSUES.md I-02). Without `confirm=true` it changes nothing; steps with no preview are listed but not checked.
- **edit__audit_log**: recent changes made through this server.

### `legacy__`: direct bridge calls (fallback)

- **legacy__get_state**: Resolve version, page, project, timeline, fps, frame range, playhead.
- **legacy__list_timelines**: names of all timelines in the project.
- **legacy__set_current_timeline**: switch the active timeline.
- **legacy__create_timeline**: new timeline, empty or from Media Pool clips.
- **legacy__duplicate_timeline**: duplicate the current timeline under a new name.
- **legacy__list_timeline_items**: items on the current timeline's video, audio or subtitle tracks.
- **legacy__list_media**: all Media Pool clips (id, name, duration, fps, resolution, path).
- **legacy__import_media**: import files from disk into the Media Pool.
- **legacy__append_clips**: append clips with a source range and record frame.
- **legacy__delete_items**: delete timeline items, optionally rippling (needs `confirm`).
- **legacy__add_track**: add a video or audio track.
- **legacy__add_text_plus**: insert editable Text+ titles at frames with text and style.
- **legacy__style_text_plus**: change existing Text+ titles: text, font, style, size, position.
- **legacy__set_item_properties**: transform/composite properties (zoom, pan, opacity, crop, ...).
- **legacy__set_grade**: primary grade (ASC CDL slope/offset/power, saturation).
- **legacy__set_lut**: load a .cube LUT onto a node.
- **legacy__refresh_luts**: rescan LUT folders.
- **legacy__probe_color**: report which colour-page calls Resolve exposes for an item.
- **legacy__add_marker**: add one timeline marker.
- **legacy__delete_marker**: delete the marker at a frame.
- **legacy__list_markers**: all timeline markers by frame.
- **legacy__goto_timecode**: move the playhead.
- **legacy__open_page**: switch Resolve page (media, cut, edit, fusion, color, fairlight, deliver).
- **legacy__export_frame**: return the frame at a timecode as an image.
- **legacy__save_project**: save the current project.
- **legacy__list_render_presets**: available render presets.
- **legacy__queue_render**: queue the current timeline for render (doesn't start it).
- **legacy__start_render**: start queued renders (needs `confirm`).
- **legacy__render_status**: render progress and per-job status.

### `media__`: local media analysis (source files read-only)

- **media__probe_media**: ffprobe a file: duration, codecs, resolution, frame rate, audio streams.
- **media__detect_silence**: silence intervals in an audio/video file.
- **media__extract_audio**: first audio stream to a 48 kHz stereo WAV.
- **media__make_contact_sheet**: contact sheet of frames from a video.
- **media__transcribe_audio**: local transcription with faster-whisper (tiny/base/small).

### `resolve__`: upstream engine (free-Resolve subset)

- **resolve__knowledge**: editorial, colour, audio and workflow guidance and API limits (topics, get, search).
- **resolve__media_analysis**: project-scoped clip/bin/timeline analysis, vision, transcripts, index, take comparison and cut suggestions.
- **resolve__setup**: server defaults for confirmations, safe mode, analysis and updates.

## Quirks

Observed on free DaVinci Resolve 21.2.0.6 through this server's Lua bridge. Other versions may differ; re-check before relying on an item marked "verified".

### General

- On free Resolve only the `edit__`, `legacy__`, `media__` tools and `resolve__knowledge`, `resolve__media_analysis` and `resolve__setup` are available. Never call Studio-only features: they open a dialog that blocks every later call until the user closes it.
- Don't mix `legacy__` and `resolve__` timeline edits on one timeline.
- Importing subtitles by script can crash Resolve 21. Write an .srt with `edit__export_srt` and let the user import it with File > Import > Subtitle.
- Timeline frames are absolute: a timeline starting at 01:00:00:00 at 60 fps starts at frame 216000 (`legacy__get_state` gives `timeline_start_frame`). `legacy__add_text_plus` `record_frame` is absolute too.
- `legacy__export_frame` works on the Edit and Cut pages, including title-only timelines, and doesn't change the page. Use it to check text, layout and fades (a mid-fade frame shows the text dimmed).
- The agent can't hear audio and can't see Resolve's interface, only rendered frames.

### Text+ titles

- `InsertFusionTitleIntoTimeline` is the only way to create a title by script, and it behaves like the insert button:
  - **No track argument.** It goes on the Edit page's video *destination* track. Scripts can't read or set the destination; ask the user to click the wanted track (e.g. V2) in the track headers.
  - **Ripple insert.** Every clip on an unlocked track that ends after the playhead moves right by the inserted length, and trimming the title doesn't pull it back. Lock the other tracks (`lock_video_tracks`) first. `add_text_plus` refuses when something would move.
  - If the destination track is locked, Resolve refuses the insert ("Resolve refused to insert Text+").
  - On the **Cut page** the insert yields no usable item ("no Text+ tool in this title"). Switch to the Edit page (`legacy__open_page`), insert, then switch back.
- Inserted length = Preferences > User > Editing > Standard Generator Duration, and that is the longest a script can make a title. There is no `SetEnd`/`SetDuration`/`SetStart`. `SetRightOffset(n)` sets the **absolute** unused tail (`GetRightOffset` reads it), not a delta: a 600-frame title inserted at 900 reports 300; `SetRightOffset(360)` ends it 60 frames earlier and `SetRightOffset(300)` restores it (verified). So titles can be shortened and lengthened again, up to the inserted length.
- Text+ defaults to the "Semibold" style; always set `style` (e.g. Normograf only has "Regular").
- Text+ `size` is a 0–1 scale (default 0.08), not points. `x`/`y` are 0–1 with 0.5, 0.5 at the centre and y = 0 at the bottom.
- Different sizes in one title card need two Text+ clips on separate tracks.
- A title can't be moved to another track after insertion: it has no Media Pool item, so `AppendToTimeline` with `trackIndex` and `MoveClips` don't apply (and `edit__move_item` can't rebuild it).
- **Placing a title on a chosen track without the user (nested-timeline route):** create a small separate timeline, insert the Text+ there (it lands on V1, which doesn't matter), then place that timeline's Media Pool item with `AppendToTimeline` clipInfo `trackIndex`/`recordFrame`. It lands exactly on the requested track and frame, and the text stays editable by script through `GetMediaPoolItem().GetTimeline()`. `edit__add_captions` already works this way. Trade-offs:
  - In Resolve the user edits the wording by opening the inner timeline, not by selecting the clip.
  - Every placed copy shares one source, so editing one changes them all; use one inner timeline per distinct card.
  - Placements must not overlap on a track, or the append is silently rejected.
  - Never use a compound clip instead: it places correctly but cuts the script's access to the Text+.
- Use the nested-timeline route when the user wants full automation; prefer plain Text+ (user sets the destination) when they will edit the titles by hand. Source: `vendor/davinci-resolve-mcp/docs/reference/api-limitations.md` (Source Track Selector).

### Editing

- Fades are in frames (`edit__set_fades`); at 60 fps a 1 s fade is 60 frames. An end you leave out keeps its length.
- Resolve bug (free 21.2, Text+ titles): script fades are lost on restart unless the user has dragged a fade handle on that clip by hand at least once. Ask the user to do that first; after it, script fades on the clip are saved (both ends, including 0 and back). Read-back passing does not prove the fade is saved. Tried and failed: saving, Ctrl+S, script text/size changes plus save. See README "Known Resolve bug".
- `edit__move_item` and `edit__trim_item` rebuild the clip and copy grade, transform, audio levels, fades, colour, flags and markers, but not keyframes. They refuse titles and generators (no Media Pool item, Fusion comp).
- `edit__ripple_trim` shortens clip ends and pulls everything after them earlier, keeping the gaps. It works on titles because nothing is rebuilt: it trims in place (`trim_tail`), drops a filler from a Media Pool timeline into the gap, and ripple-deletes the filler. Verified: `DeleteClips(..., ripple=true)` shifts later clips on **all** tracks by the deleted length, and a title's text, fades and ID survive. Titles can't be moved directly, so this ripple trick is the only way to shift them.
- `edit__add_transition` needs Resolve 21.1+ and spare source frames on both sides of the cut.
- A writing `edit__` call stays on the timeline that was current when it started: if the user clicks another one
  meanwhile, Resolve jumps back and the result has a warning. `legacy__` calls don't do this.
- Take `edit__snapshot_timeline` before multi-step changes; it gives the user a one-step way back.

## Modifying scripts and mcp

When you encounter issues with doing tasks with existing tools, consider if it is possible to add new tool and/or fix existing script or tool. Never add/modify/delete script or tool without explicit permission of user.

### Bridge

After modification of `resolve_bridge.lua` script, copy it to **both** places it runs from, then reload it with the bridge's `reload_bridge` op:
- `%USERPROFILE%\resolve-claude-bridge\resolve_bridge.lua` (run by the console command below and by `reload_bridge`)
- `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\resolve_bridge.lua` (run by Workspace > Scripts > resolve_bridge in Resolve)

If the reload fails or the bridge stops answering, ask user to restart script in DaVinci's console:
```lua
fusion:RunScript(os.getenv("USERPROFILE").."\\resolve-claude-bridge\\resolve_bridge.lua")
```
or from the menu: `Workspace > Scripts > resolve_bridge`.

`reload_bridge` only works while the bridge is running. After Resolve starts, the user has to start the bridge once (console command or menu); no tool can do that.

### MCP server and tools

The code is the `resolve_editor` package: `tools/` (one file per area), `dispatch.py`, `schemas/`, `servers/`. Import its modules, not names from them (`session.pin`, `bridge.call_bridge()`): a copied name doesn't see the timeline pin or the test fakes.

New or changed `edit__` tools need the MCP server restarted. Until then they can be run by importing `resolve_editor.dispatch` in a Python script and calling `run(name, args)`.

Ask user to reconnect with tool via:
```bash
/mcp
```

### Testing changes

- Create tests first, fix code after, ensuring tests actually catch bugs.
- Run from the repo root: `python -m unittest`, one area with `python -m unittest tests.test_batch`, the Lua smoke test with `python tests/smoke_bridge.py`, the linter with `python -m ruff check .` and the type checker with `python -m mypy` (settings for both in `pyproject.toml`). A new test file imports `tests.support` before `resolve_editor`.
- In DaVinci, test new Resolve behaviour or code modification on a scratch timeline named `_RCE_...` (the bridge's `delete_scratch` removes it), never on the user's timeline.
- If a call fails, read the timeline back (`edit__inspect_range`) before retrying: a failed insert may or may not have left something behind.

## Commits

Never commit/push without permission.
