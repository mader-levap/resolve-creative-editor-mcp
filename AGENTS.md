# DaVinci Resolve for AI agents

Here are instructions for editing videos. If you need to code, see `docs/CODING.md`.

## Working rules

- Prefer `edit__`; use `legacy__` only for what `edit__` can't do.
- Start with `edit__timeline_summary`, then `edit__inspect_range` for just the part you will change. Don't list whole timelines repeatedly. Reads are cached for a few seconds; writes and a timeline switch clear the cache.
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

### Moving captions

- "Move this caption 3 s forward/later": find it with `edit__list_captions` (by the user's words, or by time for "this one"), then preview `edit__shift_captions` with `seconds: 3`; the later captions move too unless the user says only this one (`following: false`).
- "Back"/"earlier" is a negative shift. Ask when the direction is unclear.

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

All tools come from the `resolve-creative-editor` MCP server (71 on free Resolve; `resolve__` timeline tools need Studio and are hidden). `edit__` tools that take `confirm` return a preview first; repeat with `confirm=true` and `timeline` set to the timeline the preview names (refused if another timeline is current). The others run on the first call.

### `edit__`: checked editing (preferred)

- **edit__doctor**: check Python, FFmpeg, transcription, the upstream engine and the live Resolve bridge; after a hang, where the bridge stopped; Standard Generator Duration from Resolve's saved preferences.
- **edit__timeline_summary**: per-track counts (empty tracks listed with 0), gaps, overlaps, transitions and reused clips. Run before editing.
- **edit__inspect_range**: items between two frames/timecodes; `details` adds grade, transform, fades, speed, markers. `source_start` is in the clip's own frames; a clip at another frame rate also has `clip_fps` (`frames` stays timeline frames).
- **edit__find_media**: search the Media Pool by name (id, name, frames, fps, type).
- **edit__snapshot_timeline**: duplicate the current timeline as a timestamped backup and stay on the original.
- **edit__place_clips**: put Media Pool clips at exact frames and tracks; refuses to overwrite, also between the clips of one call. The source range is in the clip's own frames; a clip at another frame rate takes converted timeline frames (30 fps on a 60 fps timeline: twice as many), which the preview's `frames` gives.
- **edit__move_item**: move a clip (and linked audio/video) by rebuilding it with its settings; not titles. A clip at another frame rate keeps its source range.
- **edit__trim_item**: trim either end of a clip by rebuilding it with its settings; not titles. Frames are timeline frames; for a clip at another frame rate they must make whole source frames (30 fps on a 60 fps timeline: even numbers), or it refuses.
- **edit__ripple_trim**: shorten clip ends in place and pull everything after them earlier; works on titles. Refuses when a clip or transition on any track overlaps the frames being removed.
- **edit__set_enabled**: disable/enable clips (reversible alternative to deleting).
- **edit__set_fades**: video/audio fade-in/out in frames, with read-back. Only saved on clips with a hand-dragged fade (Resolve bug, see Editing below).
- **edit__add_transition**: native transition at a clip's start or end (Resolve 21.1+). Previews the cut, expected span and spare source frames (in timeline frames, also for a clip at another frame rate; unknown with a speed change); confirm makes a backup first. On a video clip, linked audio at the same cut gets a matching crossfade (`audio_type`, default `Cross Fade +3 dB`); `include_linked=false` keeps a hard audio cut, with a warning. With no linked audio, unlinked audio of the same source and range meeting the cut gets it too, with a note; other audio meeting the cut is named in a warning and left alone. Remove one with `legacy__delete_items` (no ripple) on its id.
- **edit__set_audio**: clip volume (dB) and pan, with read-back.
- **edit__normalize_audio**: normalize clips with Resolve's loudness modes (EBU R128, YouTube, ...).
- **edit__set_speed**: change clip speed (0 = freeze); doesn't ripple.
- **edit__copy_grade**: copy one clip's grade onto other clips.
- **edit__add_markers**: add several timeline markers at once, read back. Every marker needs a name.
- **edit__add_audio_markers**: mark silences or beats found in a file.
- **edit__add_captions**: editable Text+ captions at exact times, from segments or by transcribing a file. Text longer than `max_chars` (42) is wrapped onto balanced lines one under another, at most `max_lines` (2) at once, more in captions one after another; `line_split="sequence"` puts each line in its own caption instead. Captions are anchored at their bottom (`anchor`, default `bottom`): `y` is where the bottom edge sits and extra lines grow upward; `anchor="center"` centres the block on `y`. One small timeline per caption, in the `Captions (Resolve Creative Editor)` bin unless `folder` names another top-level bin; a caption longer than the inserted title (Standard Generator Duration) is placed in parts that share its text; the preview says which, from Standard Generator Duration. Style: `font`, `style`, `size`, `x`, `y`, any Text+ input in `inputs` (e.g. an outline: `Enabled2`, `Thickness2`, `Red2`...), or `match` (a title or caption id) to copy every input of that one; the other style arguments override `match`.
- **edit__list_captions**: captions placed by `edit__add_captions`, in time order: number, text, in/out, track and part ids; filter by text, time range or track.
- **edit__shift_captions**: move a caption (all its parts) by signed `seconds` or `frames`, and by default every later caption on its track (`following=false`: only this one). Other tracks stay. Refuses to land on another clip or before the timeline start; one backup per call.
- **edit__read_titles**: text, style and state of Text+ titles and captions: kind (`title` or `caption`), track, in/out, enabled, fades, text, and font, style, size, x, y, anchor, colour and outline; `all_inputs` adds every Text+ input. Select by `item_ids`, or a time range and track (default: the whole timeline).
- **edit__titles_to_captions**: replace plain Text+ titles with captions (the `edit__add_captions` kind) with the same text, frames, every Text+ input, fades and enabled state. Titles deleted (no ripple) and captions on the same track, or `keep_originals=true`: titles disabled and captions on new tracks. Preview first; one backup; keyframed inputs aren't copied.
- **edit__remove_captions**: remove captions (n from `edit__list_captions` or a part id): every part off the track, no ripple. By default with a backup, which still places the caption timelines, so they stay; `delete_timelines=true`: no backup, and each caption's own timeline is deleted unless a timeline (older backups included) still places it.
- **edit__delete_unused_captions**: delete the caption timelines no timeline in the project places any more (after captions were deleted by hand, or their backups were deleted). Preview lists them; project-wide.
- **edit__export_srt**: write an .srt from segments or a transcription (user imports it by hand); lines are split like `edit__add_captions`.
- **edit__export_timeline**: export the current timeline as OTIO, FCPXML, EDL, AAF or DRT.
- **edit__qc_file**: QC a rendered file: loudness, true peak, black/frozen frames, silence.
- **edit__batch**: run several `edit__` tools with one backup. A step's `tool` is the tool's name with or without the `edit__` prefix (`add_transition` or `edit__add_transition`). It stops after any step that isn't a success (`partial` too) and says why and what didn't run: read back, then run only what is left. An error in a step (e.g. Resolve refusing it) stops it the same way; if the backup fails, no step runs. Each step shows its verification and warnings, the batch lists every warning once with its steps, and the batch is `unverified` if any write couldn't be checked. Without `confirm=true` it changes nothing; steps with no preview are listed but not checked.
- **edit__audit_log**: recent changes made through this server.

### `legacy__`: direct bridge calls (fallback)

- **legacy__get_state**: Resolve version, page, project, timeline, fps, frame range, playhead.
- **legacy__list_timelines**: names of all timelines in the project.
- **legacy__set_current_timeline**: switch the active timeline.
- **legacy__create_timeline**: new timeline, empty or from Media Pool clips.
- **legacy__create_bin**: create a Media Pool bin by its path from the root (`Footage/Day 1`); only the last level, under an existing parent; the current bin stays.
- **legacy__use_bin**: make a bin current (`""` is the root); new clips, timelines and backups go there. Returns `previous`, for switching back. `legacy__get_state` gives `current_bin`.
- **legacy__delete_bin**: delete a bin (needs `confirm`). A bin with anything in it needs `with_contents=true`, which deletes its clips, timelines and bins too (Media Pool entries only; files stay). Refuses the root, the current bin and a bin holding the current timeline.
- **legacy__delete_timeline**: delete timelines by exact name (needs `confirm`). Refuses the current timeline and unknown names before deleting anything. `with_captions=true` also deletes the caption timelines placed on them, except ones another remaining timeline uses (kept and named). Deleting a timeline alone leaves its caption timelines in their bin.
- **legacy__duplicate_timeline**: duplicate the current timeline under a new name.
- **legacy__list_timeline_items**: items on the current timeline's video, audio or subtitle tracks. `source_start` is Resolve's left offset, in timeline frames: for a clip at another frame rate it isn't the clip's frame (`edit__inspect_range` gives that).
- **legacy__list_media**: all Media Pool clips (id, name, duration, fps, resolution, path).
- **legacy__import_media**: import files from disk into the Media Pool.
- **legacy__append_clips**: append clips with a source range and record frame.
- **legacy__delete_items**: delete timeline items, optionally rippling (needs `confirm`).
- **legacy__add_track**: add a video or audio track.
- **legacy__add_text_plus**: insert editable Text+ titles at frames with text and style.
- **legacy__style_text_plus**: change existing Text+ titles or captions: text, font, style, size, position, other Text+ inputs by id (number, string or `[x, y]`).
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
- Inserted length = Preferences > User > Editing > Standard Generator Duration, and that is the longest a script can make a title. There is no `SetEnd`/`SetDuration`/`SetStart`. `SetRightOffset(n)` sets the **absolute** unused tail (`GetRightOffset` reads it), not a delta: a 600-frame title inserted at 900 reports 300; `SetRightOffset(360)` ends it 60 frames earlier and `SetRightOffset(300)` restores it (verified). So titles can be shortened and lengthened again, up to the inserted length. The scripting API can't read the preference; `edit__doctor` reads it from `%APPDATA%\Blackmagic Design\DaVinci Resolve\Preferences\config.user.xml` (`GeneratorDurationType`, `GeneratorDurationSecs`/`GeneratorDurationFrames`), which Resolve may write only when it saves its preferences. `SetSpeed` on a title is refused (verified), so slowing it down doesn't lengthen it.
- Text+ defaults to the "Semibold" style; always set `style` (e.g. Normograf only has "Regular").
- Text+ `size` is a 0–1 scale (default 0.08), not points. `x`/`y` are 0–1 with 0.5, 0.5 at the centre and y = 0 at the bottom. Text+ centres a multi-line block on `y`; `VerticalTopCenterBottom` = 1 anchors it at its bottom instead, so extra lines grow upward (verified; `VerticalJustification*` inputs don't move the block).
- Different sizes in one title card need two Text+ clips on separate tracks.
- A title can't be moved to another track after insertion: it has no Media Pool item, so `AppendToTimeline` with `trackIndex` and `MoveClips` don't apply (and `edit__move_item` can't rebuild it).
- **Placing a title on a chosen track without the user (nested-timeline route):** create a small separate timeline, insert the Text+ there (it lands on V1, which doesn't matter), then place that timeline's Media Pool item with `AppendToTimeline` clipInfo `trackIndex`/`recordFrame`. It lands exactly on the requested track and frame, and the text stays editable by script through `GetMediaPoolItem().GetTimeline()`. `edit__add_captions` already works this way. Trade-offs:
  - In Resolve the user edits the wording by opening the inner timeline, not by selecting the clip.
  - Every placed copy shares one source, so editing one changes them all; use one inner timeline per distinct card.
  - A placement can't be longer than the inserted title; place a longer card in parts from the same inner timeline (`edit__add_captions` does this).
  - A new timeline takes the project frame rate. To give it another rate by script, set `useCustomSettings` to `"1"` first, then `timelineFrameRate`; only an empty timeline accepts it (verified).
  - Placements must not overlap on a track, or the append is silently rejected.
  - Never use a compound clip instead: it places correctly but cuts the script's access to the Text+.
- `edit__read_titles` reads a title's or caption's text and every Text+ input (about 300 on 21.2: number, point, text and FuID inputs, from `GetInputList`; keyframed ones are listed, not copied). When inputs are copied, the bridge sets only those that differ from the new Text+, so buttons (`ClearAllKerning`) and script fields are left alone (verified: a converted caption renders byte-identical to its title).
- Deleting a caption clip (by hand or `legacy__delete_items`) leaves its caption timeline in the bin. Deleting a caption timeline that a timeline still places leaves that clip Media Offline, backups included (verified). `edit__remove_captions` and `edit__delete_unused_captions` only delete caption timelines nothing places.
- Use the nested-timeline route when the user wants full automation; prefer plain Text+ (user sets the destination) when they will edit the titles by hand. Source: `vendor/davinci-resolve-mcp/docs/reference/api-limitations.md` (Source Track Selector).

### Editing

- Resolve 21.2 refuses a marker without a name, on the timeline and on clips. `edit__add_markers` and `legacy__add_marker` refuse one before sending it. Markers made by hand get a name (`Marker 1`).
- Clip marker frames count from the start of the source media, not the clip, for reading and adding (verified). Markers outside the clip's used range are kept, hidden. Resolve's marker tooltip shows source time; use the playhead to see where a marker sits on the timeline. `edit__move_item` and `edit__trim_item` keep clip markers at their source frames.
- Fades are in frames (`edit__set_fades`); at 60 fps a 1 s fade is 60 frames. An end you leave out keeps its length.
- Resolve bug (free 21.2, Text+ titles and video/audio clips): script fades are lost on restart unless the user has dragged a fade handle on that clip by hand at least once. Ask the user to do that first; after it, script fades on the clip are saved (both ends, including 0 and back). Read-back passing does not prove the fade is saved. Tried and failed: saving, Ctrl+S, script text/size changes plus save. See README "Known Resolve bug".
- `edit__move_item` and `edit__trim_item` rebuild the clip and copy grade, transform, audio levels, fades, colour, flags and markers, but not keyframes. They refuse titles and generators (no Media Pool item, Fusion comp).
- Deleting a bin makes the root bin current; `delete_bin` makes the previous current bin current again (verified).
- `edit__ripple_trim` shortens clip ends and pulls everything after them earlier, keeping the gaps. It works on titles because nothing is rebuilt: it trims in place (`trim_tail`), drops a filler from a Media Pool timeline into the gap, and ripple-deletes the filler. Verified: `DeleteClips(..., ripple=true)` shifts later clips on **all** tracks by the deleted length, and a title's text, fades and ID survive. Titles can't be moved directly, so this ripple trick is the only way to shift them.
- `edit__add_transition` needs Resolve 21.1+. Resolve refuses an unknown type, and a cut where a side the alignment needs has no unused source frames (center: both; right: after the outgoing clip); with only a few it makes a shorter transition, reported as `partial`. A refusal is a `failed` result naming the likely cause.
- A writing `edit__` call stays on the timeline that was current when it started: if the user clicks another one
  meanwhile, Resolve jumps back and the result has a warning. `legacy__` calls don't do this.
- Take `edit__snapshot_timeline` before multi-step changes; it gives the user a one-step way back.

### Transitions

- If user wants transitions between full videos, adjust actual start/end of clips yourself so transition works correctly.