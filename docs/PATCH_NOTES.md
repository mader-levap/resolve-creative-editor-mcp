# Patch notes — DaVinci Resolve MCP

## 2026-11-27

- Added: `edit__add_captions` `box` puts a dark box behind the text (Text+ shading element 4): `true` gives black at 40 %, one box per line, padding `[0.01, 0.05]`, round 0.15; an object changes `per` (`line` or `caption`), `opacity`, `color`, `padding` or `round`; `false` switches off a box copied by `match`. `line_spacing` sets Text+ LineSpacing; a box per line sets 1.25 unless given, because at 1.0 the line boxes overlap in a darker stripe (live). The defaults are the look settled live on 2026-11-27.
- Changed: `edit__read_titles` reports `line_spacing` and `box` in each style.

## 2026-11-25

- Added: `edit__read_titles` reads the text, style (font, style, size, position, anchor, colour, outline), fades and enabled state of Text+ titles and captions; `all_inputs` gives every Text+ input. Needs the new bridge script (`read_titles`).
- Added: `edit__titles_to_captions` replaces plain Text+ titles with captions that keep the text, frames, track, every Text+ input, fades and enabled state; `keep_originals=true` disables the titles and puts the captions on new tracks instead. It previews first, makes one backup and reads the captions back. Live: converted captions render byte-identical to the titles.
- Added: `edit__add_captions` takes `style`, `x`, `inputs` (any Text+ input, e.g. an outline) and `match` (copy every input of a title or caption). Before, only `font`, `size` and `y` reached Resolve.
- Changed: `legacy__style_text_plus` works on captions too, and its `inputs` take strings and points (`[x, y]`), not only numbers. An input that already has the value isn't set again. `x` without `y` now moves the text (it was ignored).
- Added: `edit__remove_captions` removes captions with all their parts. By default it makes a backup and keeps the caption timelines, which the backup places; `delete_timelines=true` makes no backup and deletes the caption timelines no other timeline places. Live: deleting a caption timeline that a backup still placed left the backup's clip Media Offline, so timelines in use are never deleted.
- Added: `edit__delete_unused_captions` deletes the caption timelines no timeline places any more, project-wide, after a preview. Needs the new bridge script (`caption_usage`).
- Added: `legacy__delete_timeline` (with `confirm`) deletes timelines by name; `with_captions=true` also deletes the caption timelines placed on them unless another timeline still uses them. Needs the new bridge script.
- Changed: the fades warning says the restart bug was also seen on video and audio clips (docs/ISSUES.md F1).

## 2026-11-24

- Added: `legacy__create_bin`, `legacy__use_bin` and `legacy__delete_bin` (with `confirm`) work with Media Pool bins by their path from the root, and `legacy__get_state` reports `current_bin`. `delete_bin` refuses a bin with anything in it unless `with_contents=true`, and keeps the current bin current (Resolve makes the root current when a bin is deleted). Needs the new bridge script.
- Added: `edit__add_captions` offers `folder`, the top-level bin for the caption timelines (default `Captions (Resolve Creative Editor)`). Fixed: its preview always named the default bin, even when `folder` named another.
- Changed: the live test works in its own `_RCE_LIVE_<time>` bin (test clip, timelines, backups, captions), deletes it with everything in it at the end, and makes the bin you had selected current again. It used to leave `rce_live_clip.mp4` in whichever bin was current.
- Added: a `bins` area in the live test (`--only bins`) checks the bin commands in real Resolve: nested bins, switching back to a non-root bin, every `delete_bin` refusal and a delete with contents. It runs first; if any of its checks fails, the other areas are skipped.
- Added: tests for what had none. Unit: the move/trim rollback when a setting isn't copied or the swap fails after one linked item, the transcription cache, every confirm guard of the gateway, `set_audio` pan, `normalize_audio`, `inspect_range` details, `export_timeline`, `audit_log`, `doctor`, and the error branches of backups, appends, `place_clips`, `ripple_trim` and `list_captions`. `tests/unit/test_media_ffmpeg.py` runs the media tools, `qc_file` and beat detection on a generated clip (skipped without FFmpeg). Live: a `ripple` area, plus `set_speed`, `copy_grade`, `normalize_audio`, `snapshot_timeline` and `batch`. They found I-26 to I-29 (docs/ISSUES.md), not fixed yet: their tests are marked `expectedFailure`, and the live checks for I-27 and I-28 fail until they are fixed.
- Fixed: `edit__place_clips` refuses clips of one call that overlap each other on a track, naming both; Resolve had placed the later one shifted and shortened (I-27).
- Fixed: when `edit__move_item` or `edit__trim_item` can't place the clip and can't rebuild the original either, the copy with the clip's settings is kept on its staging track, and the result says where it is and names the backup, instead of a bare error (I-29).
- Fixed: `edit__place_clips` refuses a source range outside the clip in its preview; before, the preview passed and the confirm failed with the bridge's error (I-28).
- Fixed: a cached transcript from `media__transcribe_audio` names the file asked for, not the one it was first made from (I-26).

## 2026-11-23

- Changed: the unit tests moved to `tests/unit/` (one area: `python -m unittest tests.unit.test_batch`) and the live test to `tests/live/live_resolve.py`, which can now run some areas with `--only`. `python -m unittest` and `python tests/smoke_bridge.py` are unchanged.
- Added: `edit__list_captions` lists placed captions with their text, times and parts, filtered by text, time or track. `edit__shift_captions` moves a caption by a signed time, all its parts together, and by default every later caption on its track; `following=false` moves only that one. It previews first, refuses to land on another clip or before the timeline start, makes one backup and reads the captions back. Needs the new bridge script (`caption_texts`).
- Changed: `edit__add_captions` and `edit__export_srt` now wrap long text onto balanced lines shown one under another in one caption, at most `max_lines` (default 2) at once; text that needs more lines continues in captions one after another. `line_split="sequence"` keeps the old behaviour, one line per caption, one after another. Captions are now anchored at their bottom edge (`anchor`, default `bottom`), so extra lines grow upward and stay in the frame; a one-line caption at the same `y` sits about half a line higher than before. `anchor="center"` keeps the old placement.
- Fixed: the live caption check assumed a 5 s Standard Generator Duration (ISSUES.md I-24). It now checks what the tool promises, for any duration. The duration is read from Resolve's saved preferences: `edit__doctor` reports it, and the `edit__add_captions` preview says which captions are placed in parts. Logged I-25: a live probe found a long caption can be one clip, with several titles inside its inner timeline; decided to keep parts.
- Fixed: the live test accepted a refused or misplaced transition as a pass (ISSUES.md I-12). It now checks a valid transition's exact span and linked audio crossfade, and the refusals seen live. Its scratch timeline is set to 30 fps, so it also runs on projects at other rates. Logged I-24: the caption length check assumes one Standard Generator Duration.
- Fixed: `edit__timeline_summary` left out empty tracks, so a newly added track couldn't be seen (ISSUES.md I-11). Every track is now listed, empty ones with 0. Needs the new bridge script.
- Fixed: a refused transition always blamed spare source frames and ended in a bare error (ISSUES.md I-09). It is now a `failed` result with the request, the checked spare frames and the likely cause (a side with none that the alignment needs, or the type). Live T3/T4 recorded what Resolve refuses and when it shortens instead. Needs the new bridge script.
- Changed: when the bridge stops answering after acknowledging a request (ISSUES.md I-22, cause still unknown), the error names the op, says a write may have been made and asks for a restart; later calls say it is still stuck instead of "not running"; `edit__doctor` shows where the stuck copy stopped (`previous_run_stuck`). A replaced copy no longer sends a late answer. Needs the new bridge script.
- Fixed: `edit__add_transition` treated `duration: 0` as "use Resolve's default" and sent negative lengths to Resolve (ISSUES.md I-08). A duration must now be a whole number of frames above 0, or left out.
- Changed: `edit__add_transition` on a video clip also adds a matching crossfade on its linked audio by default (ISSUES.md I-07), `Cross Fade +3 dB` unless `audio_type` says otherwise. `include_linked=false` keeps the hard audio cut and warns; a split edit gets a warning instead of a crossfade.
- Changed: `edit__add_transition` previews first (cut, expected span, spare source frames) and makes a backup timeline on confirm (ISSUES.md I-06). Callers must now send `confirm=true` and the previewed `timeline`. Live check: `legacy__delete_items` removes a transition without touching its clips.
- Fixed: `edit__ripple_trim` ignored transitions on other tracks (ISSUES.md I-05). A transition at a clip's edge reaching into the removed frames was deleted by Resolve while the trim said `passed`. Such a transition now blocks the trim, and the check after the trim includes transitions.
- Fixed: `edit__batch` dropped the warnings of steps that succeeded, such as the fades and grade warnings (ISSUES.md I-20), and said `passed` when a step couldn't be checked (I-18). Each step now shows its verification and warnings, the batch lists each warning once with its steps, and a batch with an unverified write is `unverified`.
- Fixed: moving or trimming a clip dropped clip markers that weren't near the start of the source, and still reported `passed` (ISSUES.md I-23). Clip marker frames count from the source start, so markers are now copied at their own frames, hidden ones included, and the check after the edit compares markers. Needs the new bridge script.
- Fixed: markers without a name were never added, and the tools blamed an existing marker (ISSUES.md I-19). Resolve 21.2 refuses them, so a name is now required: `edit__add_markers` and `legacy__add_marker` refuse an unnamed marker before sending it. Marker tools read their markers back. An unnamed clip marker is copied as `Marker` when a clip is moved or trimmed. Needs the new bridge script. Found: moving or trimming a clip drops its clip markers (I-23, not yet fixed).
- Fixed: `edit__add_transition` checked only the length, and with no `duration` nothing at all, so a wrong transition was reported as `passed` (ISSUES.md I-04). It now reads the timeline back and checks the transition's track, span, length, type, category and alignment and that no clip changed; anything that differs gives `partial`. The result gives `start`, `end` and `cut` instead of the ambiguous `at` (I-10).
- Fixed: two processes using the bridge at once (another session's server, a script) could lose requests, get another's reply or a false "Bridge not running", and an edit could run while its caller got an error (ISSUES.md I-15). Bridge calls now take turns through a file lock in the bridge folder; a call that can't get a turn within 60 s fails with "bridge busy ... nothing was sent". Restart every server and script that uses the bridge; old ones ignore the lock.
- Fixed: an error inside `edit__batch`, such as Resolve refusing a transition, lost the completed steps and the backup name and wasn't audited (ISSUES.md I-02). The batch now stops at that step and returns the steps done, the error, the steps not run and the backup. A batch whose backup fails runs no step. Writing `edit__` calls that end in an error are audited as `error`.
- Fixed: a long caption failed and took the following captions with it (ISSUES.md I-21). Each caption is now one
  small timeline, placed in parts no longer than the inserted Text+ title, at any frame rate. Needs the new bridge
  script.
- Fixed: a confirm could apply a preview to another timeline when the current one changed in between (ISSUES.md
  I-17). Previews now name their timeline, and `confirm=true` must pass it as `timeline`, or nothing is changed.
  Reads no longer describe the previous timeline for a few seconds after a switch.

## 2026-11-22

- Fixed: `edit__batch` previews could make real changes (ISSUES.md I-01). Only tools with a preview are called,
  a step can't confirm itself, and only the boolean `true` counts as `confirm` for every `edit__` tool.
- Fixed: on Resolve 21.2 every bridge reply over about 65 KB timed out, and a half-written one could crash the
  call (ISSUES.md I-13).
- Fixed: edits and backups could land on the wrong timeline when the current timeline changed (ISSUES.md I-16).
  A writing `edit__` call now stays on the timeline it started on. Needs the new bridge script.
- Fixed: `edit__batch` kept editing after a `partial` step (ISSUES.md I-03). It now stops, says why and lists
  the steps it didn't run.
- Changed: the Python code is now the `resolve_editor` package and the tests are split by area (no tool changes;
  ISSUES.md I-14 fixed). Run tests with `python -m unittest` and `python tests/smoke_bridge.py`.
- Changed: `pyproject.toml` with ruff lint settings (`python -m ruff check .`), lint findings fixed, and the three longest
  functions split (media tools, gateway tool calls, ripple trim). No tool changes.
- Changed: type checking with mypy (`python -m mypy`): every function in the package is annotated, timeline items
  have an `Item` type, and new package code must be annotated. No tool changes.

## Stage-two audit (2026-11-11)

Found and fixed, each confirmed in a real Resolve 21.1 (free) on a scratch timeline:
- Move and trim deleted the clip first and re-added it, losing grade, transform, audio levels and fades, and a failed
  re-add could lose the clip. They now build the replacement on a temporary track, copy grade (`CopyGrades`),
  properties, fades, colour, flags and markers, verify, and only then remove the original. Linked audio/video moves
  with it and is relinked. Keyframes still can't be copied: the API has no way to read them.
- Speed-changed clips, Fusion clips, take clips, mixed frame rates and clips touching a transition are refused
  instead of being replaced with the wrong source range.
- Text+ captions were always 5 s long (the API can't resize titles) and drifted at 29.97/23.976 because the frame
  rate was rounded down. Captions now use upstream's nested-timeline route for exact frames and lengths; long lines
  are split and overlaps trimmed. Timecode maths is exact, including drop frame.
- Timeline reports counted transitions as overlaps and returned every gap; they are now compact with timecodes.
- Duplicating a timeline makes Resolve switch to the copy, sometimes after the script switched back. Timeline
  switching is now verified and retried, and every confirmed edit checks the timeline didn't change underneath it.
- The bridge path in the README didn't work when setup ran inside a sandboxed app; the bridge now also lives in
  `%USERPROFILE%\resolve-claude-bridge`, and the bridge can reload itself.

Added: previews before destructive edits, `edit__batch`, read caching with invalidation, `place_clips`,
`inspect_range`, `find_media`, native fades, transitions, speed, audio volume/pan, loudness normalization,
grade copy, batch markers, timeline export (OTIO/FCPXML/EDL/AAF/DRT), SRT export and file QC.
Not added because the API can't do it: keyframes, power windows, node creation, subtitle-track placement
(scripted subtitle import crashes Resolve 21), Fairlight effects and bus routing.

## Fixed
- `add_track` now uses an explicit branch. The previous Lua `and/or` idiom could call `AddTrack("video")` when adding an audio track returned false/nil.
- `append_clips` validates source ranges, track indexes, record positions and media type before calling Resolve.
- `AppendToTimeline` ranges are treated as half-open `[start_frame, end_frame)`. `end_frame` is exclusive; default full-clip end is the source frame count. This prevents one-frame trims/gaps from inclusive-bound assumptions.
- Lua JSON decoding now handles four-byte UTF-8 code points and UTF-16 surrogate pairs, and rejects malformed unicode/control escapes.
- Smoke tests now cover the exclusive end-frame behavior and invalid zero-length ranges.

## Added
- `probe_media`: ffprobe metadata inspection.
- `extract_audio`: WAV extraction for auditioning / downstream analysis.
- `detect_silence`: FFmpeg silence intervals (not automatic edit decisions).
- `transcribe_audio`: optional faster-whisper transcription with word timestamps.
- `make_contact_sheet`: contact-sheet image for visual shot review.

## Verification performed here
- Python syntax compilation passed.
- MCP tool registration reports 32 tools.
- FFmpeg integration smoke-tested against a generated sample: metadata probe, WAV extraction, silence detection and contact-sheet generation passed.
- Full Lua-to-Resolve smoke test was not run: `lupa` is not installed in this environment and DaVinci Resolve is not available here.
- No live timeline edit, Fairlight operation, color grade or render was performed.

## Still missing for a genuinely professional autonomous editor
This remains a safer Resolve bridge plus media-analysis helpers, not a complete AI editor. It still needs:
- a real audio audition/perception path (transcription and waveform statistics are not listening);
- take comparison and dialogue assembly logic;
- deeper Resolve/Fairlight operations verified against the installed Resolve version;
- title/subtitle and transition workflows;
- visual grading analysis and node-level grade execution;
- render playback review and iterative correction.

Do not claim the AI listened to a file unless an audio-capable model or human actually auditioned it.

## Unified integration (2026-11-11)
- Added `unified_server.py`: one MCP stdio gateway for the upstream 37-tool compound server, the original Lua bridge, and local media-analysis tools.
- Namespaced tool families (`resolve__`, `legacy__`, `media__`) to prevent collisions.
- Retained the legacy bridge as a fallback rather than mixing two timeline controllers silently.
- Added SHA-256 + model + language keyed transcription caching; source media remains read-only.
- Added Windows setup that pins the upstream repository revision, installs its dependencies without registering a second MCP, copies the Lua bridge with backup, and writes one `.mcp.json` entry.
- Gateway routing tested against fake MCP child processes. Live Resolve validation is still required.

## Editor upgrade (2026-11-11)
- Added `editor_tools.py`: `edit__` tools with pre-checks, read-back verification, rollback and an audit log. The result envelope idea comes from upstream.
- Gateway keeps running if the upstream engine is missing, hides upstream tools that cannot work on free Resolve, and sends agent instructions at startup.
- `delete_items` and `start_render` now need `confirm=true`.
- Setup registers the server itself and adds `-Lite`, `-Studio`, `-WithTranscription` and `-NoRegister`.
