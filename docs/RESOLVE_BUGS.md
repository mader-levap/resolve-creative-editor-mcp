# Resolve bugs and quirks

Resolve behaviour this server works around, with a test for each, so it can all be re-checked when a new Resolve version comes out. Our own bugs are in `ISSUES.md`; this file is only about Resolve.

All entries were seen on free DaVinci Resolve 21.2.0.6, Windows 10, unless noted.

## How to re-test on a new version

1. Note the new version (`legacy__get_state` or Help > About).
2. Work on a scratch timeline whose name starts with `_RCE_` in a test project, never on a real edit. Delete it and its backups afterwards.
3. Run the entries in the summary table, worst first. Some need a Resolve restart (R-02, R-06) or the user's eyes (R-05); group those.
4. Where a test says "console", use Workspace > Console, Lua, and start the script with `local r = resolve or Resolve()`. Take items from a track by name (`GetItemListInTrack("video", 1)`), not with `GetCurrentVideoItem()`, which returns the topmost track's item.
5. Judge rendered frames with `legacy__export_frame`, not read-backs: several of these bugs read back correctly.
6. For each entry, update **Last checked** and the result. If the behaviour changed, follow "If it changes" and update `AGENTS.md` (Quirks), `README.md` and the code it names.
7. `tests/live/live_resolve.py` covers some of the transition, placement and caption behaviour end to end; run it too.

## Summary

| ID | Kind | What | Last checked | Our handling |
|---|---|---|---|---|
| [R-01](#r-01) | **Bug** | Scripted left/right transition renders one side black | 21.2.0.6, 2026-11-27 | `add_transition` calls on the right clip, refuses with no spare frames (I-39) |
| [R-02](#r-02) | **Bug** | Script fades are lost on restart unless a fade was dragged by hand | 21.2.0.6, 2026-11-25 | Warning on every `set_fades` result |
| [R-03](#r-03) | **Bug** | Importing subtitles by script can crash Resolve 21 | 21.x, date not recorded | No subtitle import; `export_srt` for the user |
| [R-04](#r-04) | **Bug** | Calling a Studio-only feature on free Resolve opens a dialog that blocks every later script call | 21.2.0.6, date not recorded | Studio tools hidden on free Resolve |
| [R-05](#r-05) | **Bug** | An OBS MKV flashes "Media Offline" on random frames in playback | 21.2.0.6, 2026-11 | Lossless remux to MP4 + Replace Selected Clip |
| [R-06](#r-06) | **Bug** | A media file overwritten at the same path stays Media Offline until Resolve restarts | 21.2.0.6, 2026-11-27 | None; restart |
| [R-07](#r-07) | Quirk | Resolve switches back to the copy a moment after `DuplicateTimeline` | 21.2.0.6, 2026-11-22 | Bridge pins every write to its timeline (I-16) |
| [R-08](#r-08) | Quirk | Overlapping clips in one `AppendToTimeline` are shifted and shortened, not refused | 21.2.0.6, 2026-11-24 | `place_clips` refuses overlaps (I-27) |
| [R-09](#r-09) | Quirk | `AddMarker` refuses a marker without a name | 21.2.0.6, 2026-11-22 | Name required (I-19) |
| [R-10](#r-10) | Quirk | Clip marker frames count from the start of the source media | 21.2.0.6, 2026-11-23 | Markers copied at source frames (I-23) |
| [R-11](#r-11) | Quirk | Left/right offsets are timeline frames for a clip at another frame rate | 21.2.0.6, 2026-11-26 | Converted in `inspect_range` and rebuilds (I-34, I-36) |
| [R-12](#r-12) | Quirk | Video and audio appended as separate clipInfos aren't linked | 21.2.0.6, 2026-11-26 | `place_clips` links the pair (I-37) |
| [R-13](#r-13) | Quirk | A transition on a video clip doesn't crossfade its linked audio | 21.2.0.6, 2026-11-22 | `add_transition` adds the audio crossfade (I-07) |
| [R-14](#r-14) | Quirk | `AddTransition` gives no reason when it refuses, ignores a wrong category, shortens a too-long one | 21.2.0.6, 2026-11-23 | Likely cause from spare frames (I-09) |
| [R-15](#r-15) | Limitation | `InsertFusionTitleIntoTimeline`: destination track, ripple insert, Cut page, inserted length | 21.2.0.6, 2026-11-20 | Nested-timeline captions |
| [R-16](#r-16) | Limitation | A title's length and track can't be set by script | 21.2.0.6, 2026-11-21 | `SetRightOffset`, `ripple_trim`, captions in parts |
| [R-17](#r-17) | Quirk | Text+ defaults and inputs: Semibold, justification, element 4 | 21.2.0.6, 2026-11-27 | Style always set; `Enabled*` set first |
| [R-18](#r-18) | Quirk | A timeline's frame rate changes by script only with custom settings on, and only while empty | 21.2.0.6, 2026-11-22 | Bridge sets `useCustomSettings` first (I-21) |
| [R-19](#r-19) | Unconfirmed | The bridge stopped answering once, cause unknown | 21.2.0.6, 2026-11-22 | Stage marker and hang record (I-22) |

## Bugs

<a id="r-01"></a>
### R-01 Scripted left/right transition renders one side black

**What:** `TimelineItem:AddTransition` limits the transition by the unused source frames of the clip it is **not** called on: called at the outgoing clip's end, the frames before the incoming clip; called at the incoming clip's start, the frames after the outgoing clip. With a few it makes a shorter transition. With none and alignment left or right it makes the full length, reports the right span, type and alignment, and renders one side black (right: the outgoing side; left: the incoming side). Centre is refused instead. A transition dragged by hand at the same cut is fine. Full table: `ISSUES.md` I-39.

**Test (console):** V1, clip A with at least 60 unused frames after it, then clip B starting at source frame 0, touching. Run:

```lua
local r = resolve or Resolve()
local tl = r:GetProjectManager():GetCurrentProject():GetCurrentTimeline()
local a = tl:GetItemListInTrack("video", 1)[1]
local tr = a:AddTransition({type="Cross Dissolve", category="simple", position="end", alignment="right", duration=60})
print(tr and (tr:GetStart() .. "-" .. tr:GetEnd()))
```

Export the frame 30 frames after the cut. Mirror case: A at the end of its source (no frames after it), B with 60+ frames before it; call on B with `position="start", alignment="left"` and check 30 frames before the cut.

**21.2.0.6:** both cases full 60 frames; the right case shows only B (A black), the left case only A (B black).

**Our handling:** `add_transition` (`resolve_editor/tools/clips.py`, `_call_target`, `_spare_check`) adds right at the incoming clip's start and left at the outgoing clip's end, where the limit is the side the alignment needs anyway, and refuses when that side has no unused frames.

**If it changes:** if both cases blend, the call-on switch is harmless and can stay; re-run the I-39 table to see what Resolve does with no spare frames on the needed side, then relax or keep the refusal in `_spare_check`.

<a id="r-02"></a>
### R-02 Script fades are lost on restart unless a fade was dragged by hand

**What:** `SetFades` on a Text+ title or a video or audio clip shows in the viewer, plays and reads back, but is gone after Resolve restarts, even after saving (Ctrl+S, or a save with other changes) — unless someone has dragged a fade handle on that clip by hand at least once. After one hand drag, script fades on that clip are saved, both ends, including 0 and back. One clip's hand drag doesn't help another. `ISSUES.md` F1, `README.md` "Known Resolve bug".

**Test:** a fresh clip (or Text+ title) never touched by hand, and a second one where the user drags a fade-in once. `edit__set_fades` 60/60 on both, read back, save, quit Resolve, start it again, read back and look at the timeline.

**21.2.0.6:** the fresh clip reads 0/0 and shows no fades; the hand-touched one keeps 60/60.

**Our handling:** `FADES_NOT_SAVED` warning on every `set_fades` result (`resolve_editor/tools/clips.py`); `titles_to_captions` and the manual tell the user to drag a fade once.

**If it changes:** remove the warning and the README / AGENTS.md / MANUAL.md notes.

<a id="r-03"></a>
### R-03 Importing subtitles by script can crash Resolve 21

**What:** a scripted subtitle import crashed Resolve 21. The exact call and date weren't recorded (`AGENTS.md` General, `PATCH_NOTES.md`).

**Test:** only in a throwaway project, with everything saved: import a small .srt into the Media Pool by script (`MediaPool:ImportMedia` on the .srt) and append it to a subtitle track. Record exactly which call was used and what happened.

**Our handling:** no tool imports subtitles; `edit__export_srt` writes an .srt and the user imports it with File > Import > Subtitle.

**If it changes:** a subtitle-track caption tool becomes possible; record the working calls here first.

<a id="r-04"></a>
### R-04 A Studio-only call on free Resolve blocks every later script call

**What:** calling a Studio-only feature on free Resolve opens a dialog in Resolve, and every later script call waits until the user closes it (`AGENTS.md` General).

**Test:** don't automate it. Only if a Studio-only call needs checking: have the user at the machine, make one call (e.g. an OFX transition), and note whether a dialog appears and whether `legacy__get_state` still answers.

**Our handling:** on free Resolve the `resolve__` timeline tools are hidden; transitions avoid OFX.

**If it changes:** nothing to change unless Studio-only calls start failing with an error instead of a dialog, which would make them safe to probe.

<a id="r-05"></a>
### R-05 An OBS MKV flashes "Media Offline" on random frames in playback

**What:** one of several MKVs from the same recorder flashed "Media Offline" on random frames during viewer playback; frame by frame cleared one spot while others kept failing. ffprobe decoded it cleanly and `legacy__export_frame` rendered the same frames correctly. Resolve counted 177 frames where ffprobe decoded 178 (Matroska stores 1 ms timestamps). Cause in the file not found.

**Test:** needs the user's eyes and an affected file (keep one). Import it, put it on a timeline, play it through twice and note any "Media Offline" frames.

**21.2.0.6:** random offline flashes in playback.

**Our handling:** lossless remux to MP4 with exact frame timestamps, then Replace Selected Clip (`AGENTS.md` Media files; `-copyinkf` is needed for the audio).

**If it changes:** drop the remux advice from `AGENTS.md`.

<a id="r-06"></a>
### R-06 A media file overwritten at the same path stays Media Offline until restart

**What:** on 2026-11-27, 01_show_gen.mkv was re-recorded over the same path while Resolve had it open (30 s became 13 s). Re-importing showed the new length (805 frames), but every frame rendered "Media Offline". The file decoded cleanly, had the same encoding as a working file, and only Resolve.exe held it open. Restarting Resolve fixed it.

**Test:** import a scratch recording, put it on a scratch timeline, then overwrite the file on disk with a different, shorter recording (same name and format) while Resolve is open. Re-import it or relink it, and export a frame.

**21.2.0.6:** Media Offline on every frame until Resolve restarts.

**Our handling:** none in code; suggest a restart, or a new file name, when a file that ffprobe reads fine is offline and was modified after import.

**If it changes:** drop the advice.

## Quirks

<a id="r-07"></a>
### R-07 Resolve switches back to the copy after `DuplicateTimeline`

**What:** after `Timeline:DuplicateTimeline` and switching back to the original, Resolve can make the copy current again a moment later, so edits land in the backup (`ISSUES.md` I-16 A).

**Test (console):** on a scratch timeline, `local c = tl:DuplicateTimeline("_RCE_dup")`, then `project:SetCurrentTimeline(tl)`, wait a second, and print `project:GetCurrentTimeline():GetName()` several times over a few seconds.

**Our handling:** every writing call is pinned to its timeline; the bridge switches back and checks the switch stuck (`resolve_bridge.lua`, the pin and `snapshot`).

**If it changes:** keep the pin anyway; it also guards against the user switching timelines mid-call.

<a id="r-08"></a>
### R-08 Overlapping clips in one `AppendToTimeline` are shifted and shortened

**What:** two clipInfos in one call that overlap on a track: Resolve placed the first as asked and the second after it, cut short (60-frame clips at +600 and +640 became +600 and +660 with 40 frames). Overlapping caption placements, in contrast, were silently rejected (`ISSUES.md` I-27, `AGENTS.md`).

**Test:** `legacy__append_clips` with two 60-frame clips of one call at +600 and +640 on V1 of a scratch timeline; list the items.

**Our handling:** `place_clips` refuses overlaps between the clips of one call before writing.

**If it changes:** nothing needed; update the description in `ISSUES.md` I-27 and `AGENTS.md`.

<a id="r-09"></a>
### R-09 `AddMarker` refuses a marker without a name

**What:** Resolve 21.2 refuses `AddMarker` with an empty name, on timelines and on clips. Markers made by hand get a name (`Marker 1`). `ISSUES.md` I-19.

**Test:** `Timeline:AddMarker(frame, "Blue", "", "", 1)` and the same with a name on a scratch timeline; `GetMarkers()`.

**Our handling:** a name is required (`edit__add_markers`, `legacy__add_marker`, the bridge); a clip marker without a name is copied as `Marker` in rebuilds.

**If it changes:** names can become optional again.

<a id="r-10"></a>
### R-10 Clip marker frames count from the start of the source media

**What:** `GetMarkers` and `AddMarker` on a timeline item use frames from the start of the source media, not of the clip. Markers outside the clip's used range are kept, hidden. The marker tooltip shows source time, which looks like clip-relative counting. For a clip at another frame rate they count the clip's own frames. `ISSUES.md` I-23, I-34.

**Test:** a clip from source frame 180; press M 60 frames into it by hand; `GetMarkers()` on the item gives 240. Add a scripted marker at a frame outside the used range and check it is accepted but not shown.

**Our handling:** `copy_settings` (bridge) copies clip markers at their source frames, unshifted; `move_item` / `trim_item` compare them after a rebuild.

**If it changes:** markers would shift after every move and trim; fix `copy_settings` before using the rebuild tools.

<a id="r-11"></a>
### R-11 Offsets are timeline frames for a clip at another frame rate

**What:** for a 30 fps clip on a 60 fps timeline, `GetLeftOffset` (listed as `source_start`), `GetRightOffset` and `GetDuration` are timeline frames, while `GetSourceStartFrame` / `GetSourceEndFrame`, append ranges and Media Pool frames are the clip's own frames. A 30 fps clip placed from source frame 6 lists a left offset of 12. `ISSUES.md` I-34 table, I-36.

**Test:** place a 30 fps clip from source frames 6-66 on a 60 fps scratch timeline; read `GetDuration`, `GetLeftOffset`, `GetRightOffset`, `GetSourceStartFrame`, `GetSourceEndFrame` (expect 120, 12, 470 for a 301-frame clip, 6, 66).

**Our handling:** `inspect_range` gives `source_start` from `GetSourceStartFrame` plus `clip_fps`; rebuilds convert ranges (`rebuild._source_range`); `place_clips` converts lengths; spare frames convert (I-35).

**If it changes:** the conversions in `rebuild.py`, `placement.py` and `clips._spare_frames` would double-convert; re-run the I-34 probe and adjust.

<a id="r-12"></a>
### R-12 Video and audio appended as separate clipInfos aren't linked

**What:** one clipInfo with no `mediaType` places video and audio linked, on the same track number. Video-only and audio-only clipInfos of the same clip (to put them on V3 and A1) are placed unlinked. `SetClipsLinked` links them afterwards. `ISSUES.md` I-37.

**Test:** `edit__place_clips` with two parts (`media_type` 1 on V2, 2 on A1, same clip, range and record) and `link=false`; `item_details` shows no `linked`.

**Our handling:** `place_clips` links such pairs with `link_items` and reads the links back.

**If it changes:** linking twice is harmless; update `AGENTS.md`.

<a id="r-13"></a>
### R-13 A transition on a video clip doesn't crossfade its linked audio

**What:** `AddTransition` on a video item puts the transition on the video track only; the linked audio keeps a hard cut. A second call on the audio item with `category "audio"` and `type "Cross Fade +3 dB"` adds the crossfade. `ISSUES.md` I-07, live test T5a.

**Test:** linked V1 + A1 clips with spare frames; console `AddTransition` on the video item; count the transitions on A1.

**Our handling:** `add_transition` adds the matching crossfade on linked audio, and on unlinked audio of the same source and range (I-31).

**If it changes:** `add_transition` would add a second audio crossfade or have it refused; check before relying on it.

<a id="r-14"></a>
### R-14 How `AddTransition` handles bad requests

**What** (live test T4): it returns nil with no reason when it refuses: an unknown type name ("Cross Disolve"), an audio type on a video item, centre with no spare frames on either side. A category that doesn't match the type (Cross Dissolve with `fusion`) is ignored and a normal Cross Dissolve made. A length longer than the clips (1000 frames on 300-frame clips) is shortened (to 0-600). Span rule (T2): left ends at the cut, right starts at it, centre puts the odd frame before it.

**Test:** the T4 cases from `ISSUES.md` on a scratch timeline with two 300-frame clips with plenty of spare frames; read back each result.

**Our handling:** `add_transition` turns a refusal into a `failed` result naming the likely cause from the spare frames (I-09) and checks the span against `expected_span`.

**If it changes:** if Resolve starts giving a reason, show it; if the span rule changes, update `expected_span` and the fake in `tests/support.py`.

## Limitations

<a id="r-15"></a>
### R-15 `InsertFusionTitleIntoTimeline`

**What:**
- It has no track argument: the title goes on the Edit page's video *destination* track, which scripts can't read or set. If that track is locked, Resolve refuses the insert.
- It is a ripple insert: every clip on an unlocked track that ends after the playhead moves right by the inserted length, and trimming the title doesn't pull it back.
- On the Cut page it yields no usable item ("no Text+ tool in this title").
- The inserted length is Preferences > User > Editing > Standard Generator Duration, which the scripting API can't read; it is the longest a script can make a title.

**Test:** with the destination on V2 and a clip on V1 after the playhead, insert a Text+ on a scratch timeline; check the track, whether the V1 clip moved, and the title length against the preference. Repeat on the Cut page. Check whether the API has gained a track argument or a way to read the preference.

**Our handling:** captions use the nested-timeline route (`edit__add_captions`); `legacy__add_text_plus` refuses when something would move; `edit__doctor` reads the preference from `config.user.xml`.

**If it changes:** a track argument would let captions be plain Text+ on the target track; a no-ripple insert would remove the lock dance.

<a id="r-16"></a>
### R-16 A title's length and track can't be set by script

**What:** `TimelineItem` has no `SetStart`, `SetEnd` or `SetDuration`. `SetRightOffset(n)` sets the absolute unused tail (a 600-frame title inserted at 900 reports 300; 360 ends it 60 frames earlier, 300 restores it), so a title can be shortened and lengthened again up to the inserted length, not past it. `SetSpeed` on a title is refused. A title has no Media Pool item, so `AppendToTimeline` with `trackIndex` and `MoveClips` can't move it to another track. `DeleteClips(..., ripple=true)` shifts later clips on all tracks, titles included, with their text, fades and id intact.

**Test:** on a scratch timeline, a Text+ title: try `SetEnd`/`SetDuration` (expect nil methods), `SetRightOffset` up and down with `GetRightOffset`, `SetSpeed(50)`; check whether any track-move call exists.

**Our handling:** `trim_tail` with `SetRightOffset`; `edit__ripple_trim` uses the filler + ripple delete to shift titles; captions longer than the inserted title are placed in parts (I-21, I-25).

**If it changes:** a real `SetEnd`/`SetDuration` or a track move would simplify `ripple_trim` and the caption parts.

<a id="r-17"></a>
### R-17 Text+ defaults and inputs

**What:**
- A new Text+ uses the "Semibold" style, which many fonts don't have (Normograf only has "Regular").
- `size` is a 0-1 scale (default 0.08). Text+ centres a multi-line block on `y`. `VerticalTopCenterBottom` = 1 anchors it at its bottom instead; the `VerticalJustification*` inputs don't move the block.
- Shading element 4's inputs only exist once `Enabled4` is 1.
- With a box per line and LineSpacing 1, the padded boxes overlap in a darker stripe.
- A Text+ copied onto a longer clip keeps its `GlobalIn`/`GlobalOut`, so its text stops at the old length with "No frame available for MediaOut1" (I-38).

**Test:** insert a Text+ and read its `StyleName`; set `Red4` before and after `Enabled4` = 1; set `VerticalJustificationTop` and compare a frame; place a caption with `box: true` and line spacing 1 and look at the frame.

**Our handling:** style is always set; the bridge sets `Enabled*` inputs first; `add_captions` anchors at the bottom and sets LineSpacing 1.25 with a box per line; captions never copy `GlobalIn`/`GlobalOut`.

**If it changes:** adjust the defaults in `captions.py`.

<a id="r-18"></a>
### R-18 A timeline's frame rate by script

**What:** a new timeline takes the project frame rate. `SetSetting("timelineFrameRate", ...)` works only after `useCustomSettings` is set to `"1"`, and only on an empty timeline. `ISSUES.md` I-21.

**Test:** create an empty scratch timeline; set `timelineFrameRate` to 30 without and then with `useCustomSettings` "1"; read it back. Repeat on a timeline with a clip.

**Our handling:** the bridge sets `useCustomSettings` first for caption timelines and `set_scratch_fps`.

**If it changes:** nothing needed.

## Unconfirmed

<a id="r-19"></a>
### R-19 The bridge stopped answering once

**What:** 2026-11-22, right after `create_timeline` and `set_current_timeline`, a `get_state` was acknowledged and never answered; Resolve kept working and logged a timeline backup and a project save in that second. Not reproduced in 140 rounds of the same sequence, with saves overlapping. Could be Resolve or the bridge. `ISSUES.md` I-22.

**Test:** none reliable. If it happens again, `edit__doctor` shows the bridge's last step (`previous_run_stuck`).
