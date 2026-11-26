# Issues

Found while testing `edit__add_transition`, 2026-11-22. This is the base for fixes. Fixed so far: I-01, I-02, I-03, I-04, I-05, I-06, I-07, I-08, I-09, I-10, I-11, I-12, I-13, I-14, I-15, I-16, I-17, I-18, I-19, I-20, I-21, I-23, I-24, I-26, I-27, I-28, I-29, I-30.

- Environment: free DaVinci Resolve 21.2.0.6, Windows 10, 60 fps timeline.
- Code is named by file and function, with paths from the repo root.

How each item is known:

- **Live**: seen in Resolve.
- **Fake**: reproduced with the real Python code against `FakeResolve` from `tests/support.py`, extended
  with the missing bridge ops. This proves our logic is wrong, not how Resolve reacts.
- **Code**: found by reading the code, not run.

## Summary

| ID | Severity | Issue | Known by |
|---|---|---|---|
| [I-01](#i-01) | ~~Critical~~ **Fixed** | `batch` preview makes real changes | Fake, live |
| [I-02](#i-02) | ~~High~~ **Fixed** | An error inside `batch` loses the results and backup name | Live, fake |
| [I-03](#i-03) | ~~High~~ **Fixed** | `batch` continues after a `partial` step | Live, fake |
| [I-04](#i-04) | ~~High~~ **Fixed** | `add_transition` verifies only the length | Fake, live |
| [I-05](#i-05) | ~~Medium~~ **Fixed** | `ripple_trim` ignores transitions on other tracks | Fake, live |
| [I-06](#i-06) | ~~Medium~~ **Fixed** | `add_transition` has no preview or backup | Fake, live |
| [I-07](#i-07) | ~~Medium~~ **Fixed** | Linked audio keeps a hard cut, without a warning | Live, fake |
| [I-08](#i-08) | ~~Medium~~ **Fixed** | Zero and negative durations aren't rejected | Fake |
| [I-09](#i-09) | ~~Low~~ **Fixed** | Every refusal blames spare source frames | Live, fake |
| [I-10](#i-10) | ~~Low~~ **Fixed** | `at` in the transition result is ambiguous | Live |
| [I-11](#i-11) | ~~Low~~ **Fixed** | `timeline_summary` hides empty tracks | Live, fake |
| [I-12](#i-12) | Low | The live transition test accepts a refusal as a pass | Code |
| [I-13](#i-13) | ~~Critical~~ **Fixed** | Bridge replies fail when half-written or over 65 KB | Live, fake |
| [I-14](#i-14) | ~~Low~~ **Fixed** | The gateway test writes to the real audit log | Live |
| [I-15](#i-15) | ~~High~~ **Fixed** | Two clients sharing the bridge lose or drop requests and replies | Live, fake, code |
| [I-16](#i-16) | ~~Critical~~ **Fixed** | Edits and backups can hit the wrong timeline | Live, fake |
| [I-17](#i-17) | ~~High~~ **Fixed** | A confirm isn't tied to the previewed timeline | Live, fake |
| [I-18](#i-18) | ~~Medium~~ **Fixed** | `batch` reports `passed` for unverified steps | Fake, live |
| [I-19](#i-19) | ~~Medium~~ **Fixed** | Markers without a name are never added | Live, fake |
| [I-20](#i-20) | ~~Medium~~ **Fixed** | `batch` drops the warnings of successful steps | Fake, live |
| [I-21](#i-21) | ~~High~~ **Fixed** | A long caption fails and takes the following ones with it | Live, fake |
| [I-22](#i-22) | Medium, **handled** | The bridge can stop answering, cause unknown | Live, once |
| [I-23](#i-23) | ~~High~~ **Fixed** | Moving or trimming a clip drops its clip markers, reported as `passed` | Live, fake |
| [I-24](#i-24) | ~~Low~~ **Fixed** | The live caption check assumes one Standard Generator Duration | Live, fake |
| [I-25](#i-25) | **Decided**: keep parts | A long caption is several clips; it could be one | Live probe |
| [I-26](#i-26) | ~~Low~~ **Fixed** | A cached transcript names the file it was first made from | Fake |
| [I-27](#i-27) | ~~Medium~~ **Fixed** | `place_clips` passes clips of one call that overlap each other | Live, fake |
| [I-28](#i-28) | ~~Low~~ **Fixed** | `place_clips` passes a source range past the clip's end | Live, fake |
| [I-29](#i-29) | ~~Medium~~ **Fixed** | When a move can't rebuild the original either, the error doesn't say where the clip is | Fake |
| [I-30](#i-30) | ~~Medium~~ **Fixed** | `place_clips` measures a clip in its own frames, not the timeline's | Live, code |
| [I-31](#i-31) | Low | `add_transition` skips the audio crossfade without a warning when nothing is linked | Live, code |
| [I-32](#i-32) | Low | `batch` refuses tool names with the `edit__` prefix, and its error doesn't say so | Live, code |

Order, one fix at a time, worst first: I-31, I-32; I-22 waits for the next sighting, which will now name where it stopped. Re-rank after each fix.

## Issues

<a id="i-01"></a>
### I-01 `batch` preview makes real changes (critical, fixed)

**Where:** `resolve_editor/dispatch.py` (`batch`, `_preview_step`, `run`)

**Problem:** a call without approval could change the timeline, with no backup. There were three causes:

| | Cause | Effect |
|---|---|---|
| A | The batch preview called `run()` for every step, including tools with no preview | Transitions, fades, audio levels, enable/disable, markers, snapshots and exports ran in preview, and again on confirm |
| B | A step's own `args.confirm` was passed through in the preview | Tools that have a preview (`set_speed`, `move_item`, ...) ran too |
| C | `confirm` was tested for truthiness | `"false"`, `"no"` and `1` counted as approval, also outside batch |

The old `test_batch_previews_without_writing` only covered `move_item` without an inner `confirm`, so it passed.

**Fix:** a batch preview calls only the tools in `PREVIEWABLE`, always with `confirm` false, and lists the rest as
`not_run`. Captions that need transcribing are listed too. `run()` accepts only the boolean `true` as `confirm`.

**Verified 2026-11-22:**

- `PreviewSafety` tests: every handler, inner `confirm`, non-boolean values, unknown new tools. They failed before
  the fix and pass after it.
- Live on a scratch timeline, calling the `edit__` tools from Python: previews left items, settings, markers, timelines,
  files and the audit log unchanged; a confirmed batch made one backup without the change and one transition.
- Through MCP after a server restart: a 10-step preview (8 listed, 2 previewed despite an inner `confirm`)
  changed nothing. `confirm` values `"false"`, `"true"`, `"no"` and `1`, sent as raw requests, gave previews only.

**Limits:** a preview checks each step against the current timeline, not the result of earlier steps. Tools without
a preview still write when called directly (`add_transition` has had one since I-06).

<a id="i-02"></a>
### I-02 An error inside `batch` loses the results and backup name (high, fixed)

**Where:** `resolve_editor/dispatch.py` (`batch`, `run`), `resolve_editor/session.py` (`call`)

**Problem:** `session.call()` raises on a bridge error and `batch` doesn't catch it. The caller gets only the error: not the
completed steps and not the name of the backup that was made. The failed batch isn't written to the audit log.

**Repro:** confirmed batch whose `add_transition` is refused. The backup is created, then a bare `RuntimeError`
is raised and the audit log stays empty.

**Fix:** an error in a step is caught and stops the batch like a `failed` step: the result has the steps done, the error as the step's reason with a warning to read back, `not_run` and `snapshot`, and the batch is audited. A writing `edit__` call that raises, in a batch or alone, is audited as `error` and still raises; previews and reads aren't audited. If the backup raises or doesn't succeed, the batch returns `failed` and runs no step (before, a backup that didn't succeed gave `snapshot: null` and the steps still ran).

**Verified 2026-11-23:**

- `BatchError` tests: a refusal at step 2 of 3, any exception in a step, a backup that raises or isn't made, auditing of the batch and of a single write that raises, no audit for a preview that raises. Six failed before the fix (the preview one is a guard), and each fails again when its part of the fix is removed.
- Live on scratch timelines, a batch of a marker, a transition Resolve refuses (no spare head frames) and a marker. Old code: a bare `RuntimeError`, although the first marker and the backup had been made; only the marker step was audited. New code: `partial`, step 1 `success`, step 2 `failed` with Resolve's reason, step 3 in `not_run`, the backup named and present; the marker step, the failed step (`error`) and the batch are audited.
- Through MCP after a server restart: the same batch gave the same result, with only the step 1 marker on the timeline, the backup named, and the three audit entries in `edit__audit_log`.

**Limit:** when the backup is made but Resolve doesn't return to the timeline, the error doesn't name the backup.

<a id="i-03"></a>
### I-03 `batch` continues after a `partial` step (high, fixed)

**Where:** `resolve_editor/dispatch.py` (`batch`)

**Problem:** it stopped only on `failed` and `blocked`. `partial` is what tools return when verification fails, so
later steps ran on a timeline that wasn't in the expected state. All 9 tools that can return `partial` reproduced it,
and the result dropped that step's warnings and changes, so it didn't say why it was partial.

**Fix:** a batch goes on only after `success`, `planned` or a read. Otherwise it returns the reason, the stopping
step's changes and warnings, `not_run` and the backup. Nothing is rolled back.

**Verified 2026-11-22:**

- `BatchStop` tests cover the 9 tools and every status. They failed before the fix.
- Live: after a real `partial` (two markers on one frame) the next step ran before the fix and doesn't after it.
- Live, false-stop check: a valid batch of 11 steps covering the 9 tools, with an odd-length transition, reached its
  end. A first attempt stopped correctly on a real failure, I-21.
- Through MCP after a server restart: a batch stopped at step 2 of 4 and neither later step ran. A valid batch
  with a read in the middle ran to its end. Both backups were correct.

<a id="i-04"></a>
### I-04 `add_transition` verifies only the length (high, fixed)

**Where:** `resolve_editor/tools/clips.py` (`add_transition`)

**Problem:** type, category, position, alignment and track are never compared with the request. With no
`duration`, nothing is compared and the result is still `passed`.

**Repro:** request Cross Dissolve at the end of an item at frame 1000; the fake returns `Wipe` at frame 1. The
result is `success` / `passed`.

**Fix:** before the write, `add_transition` finds the target clip (or is `blocked`) and records every clip on the timeline. After it, it reads the timeline back and compares:

- The transition, by its id: it must exist as a `transition` on the target's track type and track.
- Its length: the requested `duration`, if one was given.
- Its span: `clips.expected_span`, from the cut (the target's end for `position` end, its start for `start`), the alignment and the length (the actual one when no `duration` was given). The rule was measured live (T2): left `[cut − d, cut]`, center `[cut − ceil(d/2), cut + floor(d/2)]`, right `[cut, cut + d]`.
- Its type, category and alignment: from `item_details`, whose `GetProperty()` on a transition returns `TransitionType`, `TransitionCategory`, `TransitionAlignment` and `TransitionDuration` on 21.2. No bridge change was needed.
- Every clip: unchanged.

Any difference gives `partial` / `contradiction`, with a warning naming expected and actual. A property that can't be read gives `success` / `unverified`, with a warning naming it.

**Verified 2026-11-23:**

- `TransitionReadBack` tests (`tests/unit/test_transition.py`); `FakeResolve` now makes a transition item by the T2 rule and can misbehave. Correct transitions pass for every position, alignment and odd/even length, with and without `duration`, on video and audio. A wrong type, category, alignment, track, track type, span or length, a moved clip, or a transition not found give `contradiction`; unreadable properties give `unverified`; an unknown item is blocked before writing. They failed before the fix (except the audio pass, a guard), and each check's test fails again when that check is removed.
- Live T2 (see "Live tests"): 12 cases all matched the rule, with all four properties as requested and no clip changed.
- Live, old code: a centred 31-frame dissolve and a 30-frame audio crossfade gave `passed` with only `at`. New code: both `success` / `passed`, with `start` 01:00:04:44 / 04:45, `end` 05:15 and `cut` 05:00. Contradictions can't be provoked in real Resolve, so they are covered by the fake.
- Through MCP after a server restart, on a scratch timeline: a left-aligned 31-frame dissolve at the start of the second clip gave `success` / `passed`, `start` 01:00:04:29, `end` and `cut` 05:00. An audio crossfade with no `duration` gave `success` / `passed`, 30 frames (Resolve's choice), 04:45-05:15.

<a id="i-05"></a>
### I-05 `ripple_trim` ignores transitions on other tracks (medium, fixed)

**Where:** `resolve_editor/tools/ripple.py` (`_plan`)

**Problem:** transitions block a trim only on the same video track. On audio or other video tracks they skip the
overlap check completely, although ripple delete shifts all tracks.

**Repro:** item 1000-1100, trim 30, transition at 1080-1120. On V1 it is blocked; on A1 or V2 it previews as OK.
What Resolve then does to that transition is untested.

**What Resolve does, live 2026-11-23:** usually the clips under a transition already overlap the removed frames and block the trim. The hole is a transition with no clip under part of it: a centred Cross Dissolve at the start of a V2 clip next to a gap reached 10 frames into the gap (290-310 with the clip at 300). Trimming a V1 clip 0-300 by 30 then gave `success` / `passed`, but **Resolve deleted that transition**; the check after the trim ignored transitions, so nothing noticed. A transition wholly after the trim moved back with its clips and kept its id.

**Fix:** in `_plan`, a transition on any other track (video or audio) that overlaps the removed frames `[new_end, old_end)` blocks the trim, naming its track and time. The same-track rule (touching the item) is unchanged. The check after each trim now includes transitions, so a transition that is lost or doesn't move as planned gives `failed`.

**Verified 2026-11-23:**

- `RippleTransitions` tests (`tests/unit/test_ripple.py`): a transition at 1080-1120 on A1 and on V2 blocks a 30-frame trim of 1000-1100 (V1 stays blocked), transitions clear of the removed frames give `passed` and the later one moves back 30, and a transition left behind by the ripple gives `failed` naming it. Each part's test fails again when it is removed.
- Live on scratch timelines, old code vs new: the edge-of-gap transition above went from `passed` with the transition deleted to `blocked` ("a transition on V2 at 01:00:04:50 overlaps the frames being removed"); a dissolve over the removed frames stays blocked; a dissolve after the trim gives `passed` on both, moved back 30.

<a id="i-06"></a>
### I-06 `add_transition` has no preview or backup (medium, fixed)

**Where:** `resolve_editor/tools/clips.py` (`add_transition`)

**Problem:** it writes on the first call and takes no backup. (The timeline-switch guard it lacked came with
the I-16 fix.) There is also no tool made
for removing or changing a transition, and whether `legacy__delete_items` can remove one is untested.

**Fix:** `add_transition` is now a confirm tool (in `PREVIEWABLE`, schema has `confirm` and `timeline`). Without `confirm=true` it returns a preview and sends nothing: clip, track, position, cut, type, alignment, length (or "Resolve's default"), the expected span when a duration is given, and the unused source frames after the outgoing clip and before the incoming one ("no clip …" or "unknown …" for a gap, a title, or a clip whose frame rate or speed differs). The spare frames are information only; nothing blocks on them, since which side needs how many is unverified. With `confirm=true` and the previewed `timeline` it makes a backup timeline first (`backup=false` in a batch, which has its own) and returns `snapshot`. Callers must now send `confirm=true` and `timeline`.

**Removing a transition, live 2026-11-23:** `legacy__delete_items` (no ripple) on the transition's id removes it and leaves the clips on both tracks untouched.

**Verified 2026-11-23:**

- `TransitionPreview` tests (`tests/unit/test_transition.py`): the preview from either side of the cut shows cut, span and spare frames and writes nothing; no duration gives no span; a gap or a title gives "no clip" / "unknown"; an unknown item is blocked; confirm without `timeline` is blocked; confirm backs up before the write and returns `snapshot`. Batch preview and confirm-safety tests now cover `add_transition` as a previewable tool. Each part's tests fail again when it is removed.
- Live on a scratch timeline: the preview (cut 01:00:05:00, span 01:00:04:45-01:00:05:15, spare 1795 after and 1500 before) changed nothing; confirm made the backup timeline and the transition, `success` / `passed`; `delete_items` removed it with the clips unchanged.

<a id="i-07"></a>
### I-07 Linked audio keeps a hard cut, without a warning (medium, fixed)

**Where:** `resolve_editor/tools/clips.py` (`add_transition`)

**Problem:** a transition on a video item lands only on the video track. In test T1, A1 kept a hard cut under a
1 s dissolve and `warnings` was empty.

**Workaround:** call again on the audio item's id with `category: "audio"`, `type: "Cross Fade +3 dB"` and the
same position, alignment and length (test T5a).

**Fix:** `add_transition` on a video clip now also crossfades its linked audio at the same cut: `include_linked` defaults to true (the user's choice), `audio_type` defaults to `Cross Fade +3 dB`, with the same position, alignment and length (the video's actual length when no duration is given). Each crossfade gets the I-04 check and a `linked` row in the result. An audio refusal gives `partial`; the video transition stays and the warning names its id and the snapshot. Linked audio that isn't at the cut (a split edit) gets no crossfade and a warning; `include_linked=false` warns that the audio keeps a hard cut. The preview lists the planned crossfades. Called on an audio clip, linked video is left alone.

**Verified 2026-11-23:**

- `LinkedAudio` tests (`tests/unit/test_transition.py`): the default makes both with matching options, no duration takes the video's length, `audio_type` is used, `include_linked=false` and a split edit warn with one transition, a refused crossfade is `partial` naming the video transition, the preview lists the crossfade and writes nothing, unlinked and audio targets add nothing extra. Each part's tests fail again when it is removed.
- Live on a scratch timeline with three linked clips: the default at the first cut made a V1 Cross Dissolve and an A1 Cross Fade +3 dB, both 01:00:04:45-01:00:05:15, `success` / `passed`; `include_linked=false` at the second cut made the dissolve only, with "linked audio on A1 keeps a hard cut at 01:00:10:00".

<a id="i-08"></a>
### I-08 Zero and negative durations aren't rejected (medium, fixed)

**Where:** `resolve_editor/tools/clips.py` (`add_transition`)

**Problem:** `if a.get("duration")` treats 0 as "not given", so Resolve picks a length and the result is
`passed`. Negative values are sent to Resolve unchanged.

**Repro:** with 0 the options sent have no `duration`; with -5 they contain `-5`.

**Fix:** in `add_transition`, an omitted or null `duration` still means Resolve's default; anything else must be an integer (not a boolean) above 0, or the call is `blocked` before any read or write, naming the value. That covers the preview, the confirm and batch steps, and the linked audio crossfade (I-07), which copies the duration. The schema adds `minimum: 1`.

**Verified 2026-11-23:** `Duration` tests (`tests/unit/test_transition.py`): 0, -5, 2.5, "30" and true are blocked in the preview and on confirm with no `add_transition` or backup call; null gives Resolve's default and 1 passes; a batch stops at a step with 0 and runs nothing after it. Each part of the check fails a test when it is removed.

<a id="i-09"></a>
### I-09 Every refusal blames spare source frames (low, fixed)

**Where:** `resolve_bridge.lua` (`add_transition`)

**Problem:** `AddTransition` returns nil without a reason and the bridge always suggests missing spare frames. A
misspelled name, wrong category or unsupported item would get the same hint.

**What Resolve does** (live T3/T4, see "Live tests"): it refuses an unknown type for the item, and a side with no unused source frames at all when the alignment needs that side (center: both; right: after the outgoing clip; left was made even with none). With only a few spare frames, or a length longer than the clips, it makes a shorter transition instead, which the I-04 check reports as `partial`. A category that doesn't match the type was ignored.

**Fix:** the bridge's refusal names the request (type, category, position, alignment, length) and the causes seen live, without picking one. `add_transition` turns a refusal into a `failed` result instead of an error: the bridge's text, the spare source frames checked after the refusal, the backup name, and the likely cause from those numbers: the side with none that the alignment needs, or, when they are there, "they aren't the cause; check the type name". Other bridge errors still raise.

**Verified 2026-11-23:**

- `Refusal` tests (`tests/unit/test_transition.py`, `FakeResolve` can now refuse): `failed` with backup and spare frames, "aren't the cause" with plenty, the short side named for center but not for left, other errors still raise. The Lua smoke test checks the refusal text. Each part's test fails again when it is removed.
- Live, new bridge and code: no spare frames after the outgoing clip (center) and before the incoming one (center) each gave `failed` naming that side; "Cross Disolve" gave `failed` with "they aren't the cause; check the type name"; left alignment with none gave `passed`; 10 spare frames each for 60 gave `partial` (length 20).

<a id="i-10"></a>
### I-10 `at` in the transition result is ambiguous (low, fixed)

**Where:** `resolve_editor/tools/clips.py` (`add_transition`)

**Problem:** `at` is where the transition starts (01:00:04:30 in T1) and is easily read as the cut (01:00:05:00).

**Fix:** return `start`, `end` and `cut`. Done with I-04: the result has all three as timecodes and no `at` (tested in `TransitionReadBack`, seen live).

**Done when:** all three are in the result.

<a id="i-11"></a>
### I-11 `timeline_summary` hides empty tracks (low, fixed)

**Where:** `resolve_editor/tools/inspection.py` (`analyze`, `timeline_summary`)

**Problem:** tracks are derived from items. After `legacy__add_track` returned a count of 3, the summary still
listed only V1 and V2, so a new track can't be verified or seen.

**Fix:** the bridge's `get_state` reports `track_counts` (video and audio, from `GetTrackCount`), which the summary already reads, so no extra call. `analyze` takes the counts and lists every track, empty ones with 0. With an older bridge the summary works as before and adds a note to restart the bridge.

**Verified 2026-11-23:** `EmptyTracks` tests (`tests/unit/test_inspection.py`): added tracks show with 0 next to the counted ones; an older bridge gives item-only tracks and the note; `analyze` without counts is unchanged. The Lua smoke test checks `track_counts`. Each part's test fails again when it is removed. Live on a scratch timeline with one clip: `{A1: 1, V1: 1}`, then after adding a video and an audio track `{A1: 1, A2: 0, V1: 1, V2: 0}`.

<a id="i-12"></a>
### I-12 The live transition test accepts a refusal as a pass (low, fixed)

**Where:** `tests/live/live_resolve.py` (the `add_transition` check)

**Problem:** the check passes on `success`, `partial` or any result containing "refused". The unit tests have no
`add_transition` test at all.

**Fix:** live-test a cut with spare frames (must succeed with the exact span) and one without (record and assert
the real behaviour) separately. Add `add_transition` to `FakeResolve` with tests for the issues above.

**Done when:** the live test fails if a valid transition is refused or misplaced.

**Fix:** the fake and unit-test half came with I-04 to I-09 (`FakeResolve.transition`, `tests/unit/test_transition.py`). The live test now has its own transition section on fresh clip pairs, with expectations from T2/T3: a valid 10-frame centred Cross Dissolve must be `success`/`passed` at exactly `expected_span`, with the linked audio crossfade at the same span; no spare frames after the outgoing clip must be `failed` naming that side (centred) and made at the exact span (left); a misspelled type must be `failed` pointing at the type. The scratch timeline is also set to 30 fps, the generated clip's rate: on a 60 fps project the move, trim and transition checks were blocked by "clip frame rate differs from the timeline" (8 of 13 failed before this change).

**Verified 2026-11-23:** live run on a 60 fps project, 28 of 29 checks pass, all transition checks included; the one failure is I-24. Two one-off mutations of `add_transition` were caught: always sending left alignment (the exact-span checks fail) and a broken type name (the valid-transition checks fail).

<a id="i-13"></a>
### I-13 Bridge replies fail when half-written or over 65 KB (critical, fixed)

**Where:** `resolve_editor/bridge.py` (`_read_csv_reply`), Resolve 21.2 transport only

**Problem:** `reply.csv` was parsed with `csv.DictReader`, which had two faults. For a write, either one could show
an error for an edit Resolve had made, and a retry would make it twice.

| | Cause | Effect |
|---|---|---|
| A | The reader kept reading while Resolve wrote: empty, then the header, then no row yet | `TypeError`, the call failed at once |
| B | A CSV field is limited to 131072 characters, and the error was swallowed as a mid-write read | Every reply over about 65 KB timed out after 120 s |

B was deterministic. Estimated limits: about 70 clips for `item_details`, 320 for `list_media` and 360 items for
`list_timeline_items`.

**Fix:** read the file once and search that snapshot for `<32 hex id>:<hex>`. No CSV parsing.

**Verified 2026-11-22:**

- `BridgeReply` tests: the crash sequence, 65 KB to 5 MB replies, `call_bridge` polling through both, and every
  truncation point. The four tests for the two faults failed before the fix and pass after it.
- Live, before: a 70 KB reply timed out although `reply.csv` held all of it. After: 10, 70, 200 and 500 KB replies
  arrive exact in 0.4 s each, so Resolve doesn't truncate at these sizes.
- Live: 500 `get_state` calls in a row, no failures.
- `tests/smoke_bridge.py` passes (older Fusion.prefs transport).
- Through MCP after a server restart: normal reads work on the restarted server. 70 and 200 KB replies, sent as raw
  requests to a fresh server, arrive exact through both the edit__ and legacy__ routes.

**Limit:** a timeout after a write is still ambiguous in general, so read back before retrying.

<a id="i-14"></a>
### I-14 The gateway test writes to the real audit log (low, fixed)

**Where:** `tests/unit/test_gateway.py` (`GatewayTests`, `GatewayResilience`), `tests/support.py`

**Problem:** `test_gateway` started the gateway with the user's environment, so the gateway logged the fake
`legacy__hello` call as a successful change in the real `audit.jsonl`, and `edit__audit_log` showed it.

**Fix:** `tests/support.py` points `RESOLVE_BRIDGE_DIR` at a temporary folder, and every test file imports it before
`resolve_editor`.

**Verified 2026-11-22:**

- `tests/unit/test_isolation.py` loads each test file alone. It failed on `test_gateway` before the fix and catches a
  missing or misplaced import.
- Running all tests, each file alone and in changed orders, left the real bridge folder untouched.

**Limit:** entries that earlier test runs wrote to the real log stay there.

<a id="i-15"></a>
### I-15 Two clients sharing the bridge collide (high, fixed)

**Where:** `resolve_editor/bridge.py` (`call_bridge`), `resolve_bridge.lua` (`REQ`, `REPLY_CSV`)

**Problem:** every client uses the same `request.lua`, `request.lua.tmp` and reply slot (`reply.csv` on 21.2), with
no lock between processes. A client is any process that calls the bridge: another session's MCP server, or a script
that imports `resolve_editor` while the server is in use. A server that gets no Resolve calls doesn't interfere.

**Repro, fake:** the real `call_bridge` in a temporary folder, a simulated bridge and forced timing. A and B are two
clients making writes.

| | Timing | A gets | What ran |
|---|---|---|---|
| 1 | B overwrites A's unread request | "Bridge not running" | B only |
| 2 | B's ack replaces A's reply before A saw its ack | "Bridge not running" | **A** and B |
| 3 | B's ack replaces A's reply after A saw its ack | `TimeoutError` | **A** and B |
| 4 | A's cleanup deletes B's unread request | Success | A only, B's request is lost |
| 5 | B renames the shared `.tmp` first | `FileNotFoundError` | Nothing of A's |
| 6 | B overwrites the shared `.tmp` before A renames it | "Bridge not running" | B only |

In 2 and 3 the edit is made and an error is reported, so a retry makes it twice. "Bridge not running" also sends
the user to restart a bridge that works.

**Repro, live 2026-11-22:** processes calling the read-only `get_state` as fast as they can, with a 4 s ack timeout.
This is a stress rate, not a forecast for normal use.

| Clients | Calls | Failed |
|---|---|---|
| 1 | 60 | 0 |
| 2 | 860 | 19: 18 "Bridge not running", 1 `PermissionError` (WinError 32, file in use) |
| 2, with a file lock around `call_bridge` (candidate) | 200 | 0 |

The line that raised the `PermissionError` wasn't recorded and it didn't recur. By the code it is the write or
rename of the request (in `call_bridge`), because reading and cleanup catch `OSError`.

**Not affected, by the code:** parallel tool calls in one session. The gateway handles one request at a time and
waits for its legacy child. A bridge call gives up after 120 s, well inside the gateway's 1800 s limit for a
child's tool call.

**Fix:** `call_bridge` holds an OS file lock on `bridge.lock` in the bridge folder from writing the request to cleanup (`msvcrt` on Windows, `fcntl` elsewhere). The OS releases it if the process dies. The Lua bridge is unchanged.

- The wait is bounded (`lock_timeout`, 60 s; `doctor` 4 s). Then it raises `BridgeBusy`: "bridge busy ... nothing was sent", not "Bridge not running". `edit__` calls have no gateway timeout, so after an unbounded wait a write could run long after the client gave up on the call.
- The request and its `ts` are made after the wait, because the bridge drops requests over 60 s old.
- Each request has its own `.tmp` name, and moving it into place retries for up to 2 s if Resolve still has the previous one open (the `PermissionError` seen live).
- Fairness: the OS doesn't queue lock waiters, so a client calling back to back (a long batch) took the lock again before a waiter polling every 50 ms saw it free. In the first live run with the lock, each of two clients once waited the full 60 s. Waiters now touch a `bridge.wait.<pid>.<thread>` mark, and a client that let go under 0.2 s ago steps aside for 150 ms when it sees a mark under 0.5 s old. A dead waiter's mark goes stale in 0.5 s.

**Verified 2026-11-23:**

- `BridgeLock` tests (`tests/unit/test_bridge_lock.py`), with a fake bridge that follows the Lua main loop and real client processes: two clients making 20 calls each lose nothing and run nothing twice; a waiter that gives up sends nothing; a waiter runs once the lock is free, with a fresh `ts`; the lock is released after an error; a client calling back to back lets a waiter in five times in a row and isn't starved in turn. Without the lock the two-client test failed 3 of 3 runs with "Bridge not running", as live. Each test fails again when its part of the fix is removed (the fairness test 5 of 5); with the fix the lock tests passed 5 of 5 runs.
- Live, `get_state` as fast as possible, 4 s ack timeout: 1 client 60 calls, 2 clients 600, 3 clients 450, all without a failure, at 0.35 s per call overall in each case, so serialising costs no throughput. Before the fix, 2 clients had 19 failures in 860 calls.
- Through MCP after a server restart, while a script client made 150 `get_state` calls: `edit__timeline_summary`, `edit__inspect_range`, `edit__doctor` (`connected`), `legacy__get_state` and `legacy__list_timelines` all answered correctly, and the script client had no failures. The `edit__` calls run in the gateway and the `legacy__` calls in its child process, so three processes took turns.

**Limits:**

- Servers and scripts started before the fix ignore the lock until restarted.
- It serializes single bridge calls, not whole tools. Another client can still edit between a tool's read and its write. A timeline switch there is undone by the pin (I-16).
- After a timeout the lock is released while Resolve may still be busy, so the next call can still report "Bridge not running".

<a id="i-16"></a>
### I-16 Edits and backups can hit the wrong timeline (critical, fixed)

**Where:** `resolve_editor/dispatch.py` (`run`), `resolve_editor/session.py` (`pin`, `call`), `resolve_bridge.lua` (dispatcher, `add_title_cards`)

**Problem:** every bridge op acts on the timeline that is current when it runs, and a tool makes many bridge calls.
The old guard looked only before and after, per batch step, and only for calls with `confirm`.

| | Trigger | Effect before the fix, all reported `success` / `passed` |
|---|---|---|
| A | Resolve re-switches to the copy after a backup | Edits landed in the backup |
| B | The user switches during a batch | Later steps edited that timeline, which had no backup |
| C | The user switched under 3 s after a read (stale cache) | The backup named after one timeline copied another, then the first was edited |
| D | As C, `snapshot_timeline` alone | A wrong backup, without a warning |

A failed switch back after a backup also left the user on the backup.

**Fix:** a writing call reads the current project and timeline once and pins every bridge request to them. The bridge
switches back before the op and reports it, or doesn't run the op. `add_title_cards` checks each of its own switches.
An older bridge is refused. Previews and reads are never pinned.

**Verified 2026-11-22:**

- `TimelinePin` tests switch timelines before each bridge call of all 17 writing tools. They failed before the fix.
- `tests/smoke_bridge.py` runs the pin, its refusals and the title cards on the real Lua.
- Live with scripted switches: A to D were wrong before the fix, correct after it.
- Live: 20 normal batches on target, median 7.0 s before and 5.3 s after. Move, trim, captions, transition, fades and
  snapshot pass on a scratch timeline.
- Live: the new server code refused to write through the old bridge.
- Through MCP after a server restart: a confirmed batch and its backup are correct. Case D, sent to a fresh
  gateway as raw requests, is correct too.
- Live with real clicks: during a 40-step batch (38 s) the user kept double-clicking another timeline in the Media
  Pool. The bridge saw 8 switches and undid all 8, seven in under 1 s and the first in 2.9 s. All 40 markers landed on
  the right timeline, none on the other or in the backup, and the result had the warning.
- Live with real clicks through MCP: in a 20-step batch the user double-clicked the other timeline exactly four
  times. All four switches were logged and undone, all 20 markers landed on the right timeline, none on the other or
  in the backup. The same batch without clicks had no switch at all.
- An earlier click run through MCP was also correct, but its only warning named the backup. Most likely the user
  double-clicked the backup, not proven: the new backup takes the place of the timeline they were aiming at in the
  Media Pool, and repeated switches from one timeline give one warning.

**Limits:** a switch inside a single op can't be fully prevented. Timelines are matched by project and name, so a
rename during an edit stops it. `legacy__` tools still act on the current timeline.

<a id="i-17"></a>
### I-17 A confirm isn't tied to the previewed timeline (high, fixed)

**Where:** `resolve_editor/dispatch.py` (`run`, `_run_pinned`), `resolve_editor/session.py` (`_cached`, `drop_if_switched`)

**Problem:** `confirm=true` edits the timeline that is current at that moment. If the user switched after the
preview, tools that work by position (`place_clips`, markers, captions) apply the approved plan to another timeline.
Reads can also describe the previous timeline for up to 3 s after a switch by hand.

**Fix:** a preview of the 9 tools that take `confirm` (`dispatch.CONFIRMABLE`) returns `timeline`. `confirm=true`
must pass it back as `timeline`; a missing or different name is blocked before anything is written. Batch steps are
covered by the batch's own `timeline`. `timeline_summary`, `inspect_range` and `find_media` first ask which project and
timeline are current and drop the cache if that changed.

**Verified 2026-11-23:**

- `ConfirmNamesTimeline` tests, for all 9 tools: the preview names its timeline, a confirm without it or after a
  switch writes nothing and makes no backup, a confirm on the previewed timeline runs. Reads re-read after a switch
  and reuse the cache otherwise. They failed before the fix, and each fails again when its part of the fix is removed.
- Live on scratch timelines, old code: a `place_clips` confirm after a switch placed the clip on the other timeline
  and reported `success`, and `timeline_summary` described the previous timeline after a switch. New code: the
  confirm is refused and nothing is placed on either timeline; without `timeline` it is refused; with the right name
  it places; the summary follows the switch at once.
- Through MCP after a server restart: the preview names its timeline; the confirm after a switch and the one
  without `timeline` are refused and leave both timelines empty; the right name places the clip.

<a id="i-18"></a>
### I-18 `batch` reports `passed` for unverified steps (medium, fixed)

**Where:** `resolve_editor/dispatch.py` (`batch`)

**Problem:** verification is derived from the step statuses. A batch with only `copy_grade`, which can't be read
back and returns `unverified`, reports `passed`.

**Fix:** a batch that ran to its end is `unverified` if any step that succeeded was `unverified`, otherwise `passed`; reads and `planned` steps don't count. A stopped batch stays `contradiction`. Each step's row now shows its `verification`. Fixed together with I-20, in the same loop.

**Verified 2026-11-23 (with I-20):**

- `BatchReport` tests (`tests/unit/test_batch.py`): a batched `set_fades` keeps its warning in its row and in the batch's warnings, two moves list "keyframes are not copied" once for steps 1 and 2, a batch with `copy_grade` is `unverified` while markers plus a read are `passed`, and a stop is still `contradiction` with the stopping step's changes. They failed before the fix (the `passed` case is a guard), and each part's test fails again when it is removed.
- Live on scratch timelines, a batch of `set_fades`, `copy_grade` and `add_markers`. Old code: `success` / `passed`, no warnings. New code: `success` / `unverified`, with the fades warning (step 1) and the grade warning (step 2), and each step's verification.

<a id="i-19"></a>
### I-19 Markers without a name are never added (medium, fixed)

**Where:** `resolve_bridge.lua` (`add_marker`, `add_markers`), `resolve_editor/tools/markers.py` (`add_markers`)

**Problem:** Resolve 21.2 refuses `AddMarker` with an empty name, which is the default. `edit__add_markers` then
returns `partial` with "a marker already exists at some of those frames", and `legacy__add_marker` returns
`ok: false`.

**Repro, live:** on a scratch timeline at free frames, three unnamed markers through `add_markers` and one through
`add_marker` were refused. Named ones were added.

**Fix:** a name is required instead of invented (the user's choice). `edit__add_markers` refuses a marker without a non-blank name before sending anything (`blocked`, naming which), and the bridge's `add_marker` and `add_markers` raise "marker needs a name" for one, writing none; both schemas require `name`. `get_state` reports `named_markers`. `add_markers` and `add_audio_markers` now read the markers back with `list_markers` (frames taken before the call don't count) instead of trusting the bridge's count, and a refusal names the markers without claiming one cause.

Clip markers: Resolve 21.2 refuses an unnamed marker on a clip too (live probe with the test-only bridge op `scratch_clip_marker`, `_RCE_` timelines only). Markers made by hand get a name (`Marker 1`), so an unnamed one only exists if its name was cleared. For that case `copy_settings` copies it with the name `Marker` and `move_item` / `trim_item` warn; before, the whole move or trim would fail. That path can't be created by script, so it is tested with the fake only.

**Verified 2026-11-23:**

- `Markers` tests (`tests/unit/test_markers.py`) and a `Replace` test: unnamed or blank markers blocked with nothing sent, named ones read back, refusals and a lying bridge count give `partial` naming the markers, audio markers read back, a batch with an unnamed marker stops without writing, renamed clip markers give a warning. The Lua smoke test checks the bridge refusals. Each part's tests fail again when it is removed.
- Live on scratch timelines, new bridge and code: unnamed → `blocked`, nothing added; named → `success` / `passed`; a second marker on a taken frame → `partial` naming it; raw `add_marker` without a name → "marker needs a name".
- Through MCP after a server restart: the same four results with `edit__add_markers` and `legacy__add_marker`.

<a id="i-20"></a>
### I-20 `batch` drops the warnings of successful steps (medium, fixed)

**Where:** `resolve_editor/dispatch.py` (`batch`)

**Problem:** only the step a batch stops at keeps its warnings. `set_fades` warns that script fades can be lost on
restart and `copy_grade` that grades can't be read back. Inside a batch neither warning is shown.

**Repro, fake:** each tool returns one warning alone and none in a batch.

**Fix:** every step's row keeps its `warnings`, and the batch's own warnings list each one once with the steps that gave it, e.g. "steps 1, 2 (move_item): keyframes are not copied". `changes` stays only on the step the batch stops at. Verified with I-18 (see there).

<a id="i-21"></a>
### I-21 A long caption fails and takes the following ones with it (high, fixed)

**Where:** `resolve_editor/tools/captions.py` (`MAX_CARD_FRAMES`, `caption_cards`), `resolve_bridge.lua`
(`add_title_cards`)

**Problem:** two faults together.

| | Cause | Effect |
|---|---|---|
| A | Every continuation card of a caption gets the same timeline name (`caption 0002+`) | From three cards on, Resolve refuses the name. `add_title_cards` stops there, so every later caption is missing too |
| B | The 5 s card limit is written as 150 frames, which is 5 s only at 30 fps | At 60 fps cards are 2.5 s, so any caption over 5 s hits A. At 30 fps it takes over 10 s |

**Repro, live 2026-11-22, 60 fps:** a 1 s and a 6 s caption placed 2 of 4 cards, with `partial` and "could not create
timeline ... caption 0002+". A 4 s caption (two cards) works.

**Fix:** one card, and one small timeline, per caption, so no names repeat; a long timeline name is cut before the
caption number. The bridge sets the caption timeline to the target's frame rate (with custom timeline settings on),
reads how long the inserted title is, and places the caption in parts no longer than that, all from its one timeline.
`get_state` reports `caption_parts`; an older bridge is refused. A caption counts as placed only when its parts cover
it without gaps. `set_scratch_fps` (test-only, `_RCE_` timelines) sets the rate of an empty scratch timeline.

**Verified 2026-11-23:**

- Tests: at 24, 30 and 60 fps a 12 s caption and the next one are placed in full; names stay unique; an old bridge
  is refused; a refused part gives `partial`; gaps don't count. The Lua smoke test places a 400-frame card from a
  150-frame title in 150 + 150 + 100 at the right frames, at the target's rate. They failed before the fix.
- Live, old code, 60 fps, 12 s caption: `partial`, 150 of 720 frames placed, the next caption missing, "could not
  create timeline ... caption 0001+".
- Live, new code, at 24, 30 and 60 fps on scratch timelines: a 40 s caption in three parts (15 s, the inserted title
  length here) and the caption after it, exactly in place; exported frames show the text in the last part and in the
  next caption. Resolve changes a timeline's rate by script only with `useCustomSettings` on.
- Through MCP after a server restart, 60 fps: a 20 s caption in 15 s + 5 s parts and the next caption in place,
  `success` with `captions_added` 2 and `parts` 3.

<a id="i-22"></a>
### I-22 The bridge can stop answering (medium, cause unknown, handled)

**Where:** `resolve_bridge.lua` (main loop or a Resolve API call in it)

**Seen once, live 2026-11-22 20:11:58:** right after `create_timeline` and `set_current_timeline`, an unpinned
`get_state` was acknowledged and never answered. Later requests got no ack until the user restarted the bridge.

- Resolve kept responding, showed no dialog and logged no error. The bridge printed no error in the console, so it
  looks like a hang rather than a crash.
- Resolve's log has a timeline backup and a project save in that second, then "Application state changed to
  Active". The user wasn't using Resolve.
- That bridge copy had been started by `reload_bridge` 37 minutes earlier, with the I-16 change. Whether either
  matters is unknown.

**Not reproduced:** 40 repeats of the same sequence (202 calls, at most 1.3 s each) on a bridge started by the user.

**Workaround:** restart the bridge, then read the timeline back. A write that hangs like this may have been made.

**Not reproduced either, 2026-11-23:** 100 rounds of the same sequence on a bridge started by `reload_bridge`, with `save_project` every 10 rounds to overlap a save: no hang, slowest call 1.68 s.

**Handled 2026-11-23** (the cause is still unknown, so this stays open until the next sighting):

- **Where it stops:** the bridge loop records each step (ack, pin, op, reply, idle, reloading) with the op and time in Fusion's in-memory data `claude_bridge_stage`. A copy started while another was stuck reports that copy's last step as `previous_run_stuck` in `get_state` (and `edit__doctor`), and logs it; `stage_marker` flags the feature.
- **Restart while stuck works:** live, with the test-only op `scratch_stall` (scratch timelines only) sleeping inside an op, the user restarted the bridge from Workspace > Scripts > resolve_bridge; the new copy answered at once and reported `{op: scratch_stall, phase: op}`. No Resolve restart is needed. The Console showed nothing when started from the menu, so `edit__doctor` is the place to look.
- **Late answers:** a replaced copy that wakes up later no longer sends its stale answer (it could overwrite the newer copy's reply and time out a call); it stops instead.
- **Python reaction:** an acked call that never gets an answer raises an error naming the op and time, saying a write may have been made, and asking for a restart, `edit__doctor` and a read-back. It records `bridge_hang.json` in the bridge folder; while that exists, calls with no ack say the bridge is still stuck since that op, instead of the first-start text; the next answer removes it. `edit__doctor` shows the record and `previous_run_stuck`.

**Verified 2026-11-23:**

- `tests/unit/test_bridge_hang.py`: a fake bridge that acks and hangs gives the timeout text, the record, the "still stuck" text, and clears it after a restart; without a hang the usual text stays; doctor shows both records. The Lua smoke test checks the stages, `previous_run_stuck` after a stuck run (not after idle or reloading), the stall in the marker, `scratch_stall` refused off scratch timelines, and that a replaced copy stays silent (it answered before that change). Each part's test fails again when it is removed.
- Live: an 8 s timeout on a 30 s stall gave the timeout text and the record, the next call said "still stuck since scratch_stall at …", and the first answer after the stall cleared it; the restart-while-stuck result above. With the final bridge, a second restart during a 300 s stall: 210 calls to the new copy across the old copy's wake-up all answered, and the old copy never sent its stale answer.
- Through MCP after a server restart: `edit__doctor` reports `stage_marker`.

<a id="i-23"></a>
### I-23 Moving or trimming a clip drops its clip markers (high, fixed)

**Where:** `resolve_bridge.lua` (`copy_settings`), `resolve_editor/tools/replace.py` (`_replace`, `_matches`)

**Problem:** clip marker frames from `GetMarkers` seem to count from the start of the source media, not of the clip. `copy_settings` treats them as clip frames: it shifts them by `marker_shift` and copies only those from 0 to the clip's length, skipping the rest without reporting a failure. The check after a move or trim doesn't compare markers, so the result is still `success` / `passed`.

**Repro, live 2026-11-23:** on a scratch timeline, a 300-frame clip from source frame 180 (video and linked audio). The user pressed M on it; Resolve stored `Marker 1` at frame 348 on both items. `edit__move_item` through MCP reported `success` / `passed`; both new items had no markers. A scripted clip marker at frame 15 survived an earlier move only because 15 < 300.

**Frame basis, live probe 2026-11-23:** clip marker frames count from the start of the source media, for `GetMarkers` and `AddMarker` alike. On clip A (source 180-480 at 01:00:00:00) and B (source 1500-1800 at 01:00:05:00), hand markers pressed 60 frames into each clip read back at 240 and 1560 (on the video and the linked audio item). Scripted markers at 30, 60, 200, 250, 600 and 2000 on A and 50, 1550 on B were all accepted; by the playhead, the user saw only 200 at 01:00:00:20, 250 at 01:00:01:10 and 1550 at 01:00:05:50, so the others sit hidden outside the used range. Resolve's marker tooltip shows the marker's source time (200 → 03:20, 1550 → 25:50), which looks like clip-relative counting but isn't.

**Fix:** `copy_settings` copies every clip marker at its own frame: no shift, no filter, so a trim keeps markers it trims away hidden, as Resolve does. A refused `AddMarker` stays in `failed` (the I-19 rename fallback kept). `marker_shift` is gone. The check after a move or trim (`_matches`) also compares markers by frame and name, so a lost one gives `partial` naming it. `get_state` reports `clip_markers_by_source`; `move_item` and `trim_item` refuse an older bridge before writing.

**Verified 2026-11-23:**

- `ClipMarkers` tests (`tests/unit/test_replace.py`), with clip markers in `FakeResolve`: a move and a head/tail trim keep markers at their source frames, including ones near the ends and hidden ones, with no shift sent; a marker lost in the copy gives `contradiction`; an older bridge is refused. The Lua smoke test copies markers at 5, 348 and 2000 onto a 10-frame clip, the unnamed one as `Marker`; on the old Lua only frame 5 was copied and nothing was reported. Each part's test fails again when it is removed.
- Live, new bridge and code, on the probe timeline: moving A to 01:00:12:00 and trimming 30 frames off B's head gave `success` / `passed`, and all four items kept every marker at the same source frame. The user confirmed by the playhead that the hand and scripted markers sit on the same pictures.
- Through MCP after a server restart: `edit__move_item` (A back to 01:00:00:00) and `edit__trim_item` (40 frames off B's tail) gave `success` / `passed` with all markers kept.

<a id="i-24"></a>
### I-24 The live caption check assumes one Standard Generator Duration (low, fixed)

**Where:** `tests/live/live_resolve.py` ("caption lengths 45/150/54")

**Problem:** the check expects the 204-frame caption in two parts, 150 + 54, which holds only when Resolve inserts a 150-frame title (5 s at 30 fps). On 2026-11-23 it came back as 45 and 204 (one part): the user's Standard Generator Duration is 15 s, and caption timelines take the target's rate (I-21), so the inserted title was 450 frames. "captions placed with exact lengths" passed.

**Fix:**

- New `resolve_editor/prefs.py` reads Standard Generator Duration from Resolve's saved preferences, which the scripting API doesn't expose: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Preferences\config.user.xml`, `GeneratorDurationType` (`DURATION_IN_SECONDS` or `DURATION_IN_FRAMES`) with `GeneratorDurationSecs` or `GeneratorDurationFrames`. Only read; `None` when it can't be. `RESOLVE_USER_PREFS` overrides the path, and the tests point it at a file that doesn't exist, so they never read the user's settings. Resolve may write the file only when it saves its preferences, so a change in the current session may not show yet; the bridge still measures the inserted title when it places captions.
- `edit__doctor` reports `standard_generator_duration`. The `edit__add_captions` preview says how many captions will be placed in parts and in how many.
- The live test checks what the tool promises: each caption covers its time without gaps, every part but the last is one title long, and the last no longer. When the preference can be read, the long caption is made 2 s longer than it and the inserted title must match it.

**Verified 2026-11-23:**

- `tests/unit/test_prefs.py`: seconds and frames, a missing file, missing entries and broken XML, the doctor report, the preview note (1 caption in 3 parts for 40 s at 15 s and 30 fps) and no note without the preference. Each part's test fails again when it is removed, including pointing the tests at the real file.
- Live: `tests/live/live_resolve.py` 31 of 31 on a 60 fps project, including "inserted title matches Standard Generator Duration (450 frames)". With the preference patched to 10 s, that check fails.

<a id="i-25"></a>
### I-25 A long caption is several clips; it could be one (decided: keep parts)

**Where:** `resolve_bridge.lua` (`add_title_cards`), `resolve_editor/tools/captions.py`

**Now:** a caption longer than the inserted title (Standard Generator Duration) is placed as several clips back to back on the target, all from its one inner timeline (I-21).

**Probe, live 2026-11-23** (30 fps scratch timelines, 15 s title, a 40 s caption):

| | Method | Result |
|---|---|---|
| A | Three Text+ back to back inside the caption's own inner timeline (450 + 450 + 450), then the inner timeline placed once, 1200 frames | **Works.** One clip of 1200 frames on the target. Frames at 5, 445, 455, 895, 905 and 1195 are pixel-identical, so the inner cuts don't show. Fades on the outer clip read back 15/15. `style_text_plus` changed the text of all three inner titles, and the frame showed the new text |
| B | `SetSpeed` 37.5 % with `RippleTimeline` on the inner title | Refused (`ok: false`, speed stays 100 %), title stays 450 frames |
| C | Lengthen a title past the inserted length (`SetEnd`/`SetDuration`, a negative `SetRightOffset`) | Not tried: no bridge op does it, and AGENTS.md already records there is no `SetEnd`/`SetDuration` |

**Choice:** A would make every caption one clip on the target. The costs are: in Resolve, changing a long caption's wording by hand means changing each title inside its inner timeline; Text+ animation restarts at each inner cut (a static caption, as now, looks the same); and the inner insert is a ripple insert, harmless only because the inner timeline holds nothing else. Needs a bridge change, so it waits for the user's decision.

**Decision 2026-11-23:** keep parts. Each part is the caption's one inner timeline, so editing its text there changes every part, and nothing changes in the bridge. The probe results stay here in case it comes up again.

<a id="i-26"></a>
### I-26 A cached transcript names the file it was first made from (low, fixed)

**Where:** `resolve_editor/media.py` (`_transcribe_audio`)

**Problem:** the cache is keyed by the file's content, model and language, and the whole result is stored, `path` included. A second file with the same content (a copy, or the same recording under another name) gets the first file's `path` back, with `cache_hit: true`. Anything that uses `path` from the result points at the other file.

**Found 2026-11-24** by `tests/unit/test_media.py` `test_a_cached_transcript_names_the_file_asked_for`: transcribe `talk.wav`, copy it to `copy.wav`, transcribe the copy; `path` is `talk.wav`.

**Fix:** on a cache hit, `path` is set to the file asked for, like `cache_hit` and `note`. The segments, model, language and `source_sha256` stay: they describe the content, which is the same. The cache file keeps the path it was made from. It is only read back through that branch, so old cache files need no change.

**Verified 2026-11-24:** the test now also transcribes the first file again after the copy. Each gets its own path, from one transcription. It failed before the fix, and it fails again without the new line or with the cached path kept. Not checked through MCP: faster-whisper isn't installed here, and transcription doesn't touch Resolve.

<a id="i-27"></a>
### I-27 `place_clips` passes clips of one call that overlap each other (medium, fixed)

**Where:** `resolve_editor/tools/placement.py` (`place_clips`)

**Problem:** each clip is checked only against what is already on the timeline, not against the other clips of the same call. The preview passes two clips that overlap each other, and the confirm places them.

**Live 2026-11-24** (`tests/live/live_resolve.py`, clips area, 30 fps scratch timeline): two 60-frame video clips at +600 and +640 on V1 in one call. Resolve placed the first at +600 (60 frames) and the second at +660, cut to 40 frames. The tool reported `partial` with `clips_placed: 1`, because its read-back looks for the second at +640. So it isn't the silent rejection AGENTS.md describes for overlapping caption placements: Resolve places a different clip than asked.

**Found** by `tests/unit/test_timeline_steps.py` `test_clips_of_one_call_that_overlap_each_other_are_refused`, and by the live check "I-27: ...".

**Fix:** the plan loop checks each clip, for each kind it places, against the clips planned before it in the same call. On the same kind and track, overlapping spans are blocked before anything is written, naming both clips by their place in the call, the track and the time ("clip 2 (a.mp4) would overlap clip 1 (a.mp4) on V1 at ..."). Clips that only touch end to start pass, and so does the same span on another track or as video-only and audio-only. A clip with video and audio is refused once, on its video track. The tool and schema descriptions say so.

**Verified 2026-11-24:**

- `tests/unit/test_timeline_steps.py` `PlaceClips`: the overlap is refused naming both clips; touching clips, another track, and video-only with audio-only pass; overlapping video + audio clips are refused once, naming V1. The two refusal tests failed before the fix. Each of four breaks is caught: no check, `<=` for `<`, ignoring the kind, ignoring the track.
- Live: the full `tests/live/live_resolve.py` run, 63 passed. "I-27: clips of one call overlapping each other are refused" passes and nothing is placed at +600. The only failure is the I-28 check.

<a id="i-28"></a>
### I-28 `place_clips` passes a source range past the clip's end (low, fixed)

**Where:** `resolve_editor/tools/placement.py` (`place_clips`)

**Problem:** the preview doesn't compare `end_frame` with the clip's length; `move_item` and `trim_item` do (`_plan_replace`). The confirm then fails with an error from the bridge, not a `blocked` result.

**Live 2026-11-24:** source 300-420 of the 360-frame test clip. Preview: passed. Confirm: `RuntimeError: clips[1] exclusive end_frame exceeds source duration (360 frames)` from the bridge's own check in `append_clips`; nothing was placed. So no harm is done, but the approved preview was wrong and the error comes after the user's confirm.

**Found** by `tests/unit/test_timeline_steps.py` `test_a_source_range_past_the_clip_is_refused`, and by the live check "I-28: ...".

**Fix:** the preview checks the range against the clip's length, like `_plan_replace`. A negative `start_frame`, or an `end_frame` past the clip's length, is `blocked`: "source range 250-400 is outside the clip (0-300)". `end_frame` is exclusive, so ending exactly at the clip's length passes. When the Media Pool gives no length, the bridge's own check is still the only one. The schema text says the range must be inside the clip.

**Verified 2026-11-24:**

- `tests/unit/test_timeline_steps.py` `PlaceClips`:
  - an end past the clip and a negative start are refused (both failed before the fix);
  - an end at the last frame passes, and so does a clip of unknown length.
  Each of four breaks is caught: no end check, `>=` for `>`, no negative-start check, no guard for an unknown length.
- Live: the full `tests/live/live_resolve.py` run, 68 of 68, with "I-28: a source range past the clip's end is refused" passing and nothing placed.

<a id="i-29"></a>
### I-29 When a move can't rebuild the original either, the error doesn't say where the clip is (medium, fixed)

**Where:** `resolve_editor/tools/replace.py` (`_replace`, the `except` after the swap)

**Problem:** `move_item` and `trim_item` delete the original only after a copy with its settings is ready on a staging track. If placing the new clip fails, they rebuild the original from the staged copy. If that rebuild fails too, `append_one` raises "append to video 1 at 1000 did not land" out of the tool. By then:

- the original is gone;
- the staged copy, with the clip's settings, is the only one left, on a staging track (V2 in the test);
- the staging track isn't removed, and the error says none of this.

The backup timeline still has the original, if one was made.

**Found 2026-11-24** with the fake: `tests/unit/test_timeline_steps.py` `test_when_the_original_cant_be_rebuilt_either_the_result_says_where_the_copy_is` . Its fake ignores both appends on V1. Not seen live; it needs Resolve to refuse two appends in a row.

**Fix:** the rollback moved to `_roll_back`, which rebuilds each clip on its own:

- A clip that can't be rebuilt keeps its staged copy. That includes a rebuilt clip that wouldn't take the settings, whose bare item is deleted. The staging track holding the copy is kept too.
- The result is `failed` / `contradiction`. The reason names each such clip with its track and time ("its copy with its settings is on V2 at ..."), and names the backup timeline, or says no backup was made. `changes` has `rebuilt` and `kept_on_staging`.
- A new clip already placed that can't be removed again is a warning naming it, and the rebuild still runs.
- Clips that were rebuilt are linked only when more than one was. When every clip is rebuilt, the result is as before.

**Verified 2026-11-24:**

- `tests/unit/test_timeline_steps.py` `Appends`, with the fake:
  - neither the swap nor the rebuild lands;
  - the backup is named;
  - a linked pair where only the audio can't be rebuilt (video rebuilt and its staging track removed; audio copy kept on A2; no link);
  - the rebuilt clip won't take the settings;
  - a placed clip can't be removed.
  All five failed before the fix with the bare error. Each of six breaks is caught: no `try` around a rebuild or a removal, every staged copy deleted, the staging track deleted, the bare item kept, a link with one clip.
- Live, `tests/live/live_resolve.py` clips area: a `move_item` with both appends on V1 refused by the test. In real Resolve the copy was on the staging track at the new place, the result named that track, and the track was still there. The probe then removed both. Full run: 67 passed; the only failure is the I-28 check.

<a id="i-30"></a>
### I-30 `place_clips` measures a clip in its own frames, not the timeline's (medium, fixed)

**Where:** `resolve_editor/tools/placement.py` (`place_clips`)

**Problem:** the source range is in the clip's own frames, and the tool uses `end_frame - start_frame` as the clip's length on the timeline. When the clip's frame rate differs from the timeline's, Resolve converts it: a 30 fps clip on a 60 fps timeline takes twice as many frames. Both overlap checks use the unconverted length: against the timeline (`timeline.collides`) and between clips of one call (I-27). So a clip with a lower frame rate than the timeline can pass both checks and still run into the next item, which Resolve then shifts and shortens (I-27) or rejects. The preview's `frames` is wrong too. The read-back compares only the start frame, so it can't see a wrong length.

**Live 2026-11-26** ("LiL - dev log 01", "Dev Log 01", 60 fps): "Wet, wet everywhere.mp4" (1696×868, 30 fps), source 0-60. The preview said `frames: 60`; Resolve placed it as 120 frames. Nothing broke only because the record frames were worked out by hand for 120.

**Found** while appending b-roll; the code path read afterwards.

**Fix:** `place_clips` converts each clip's source length to timeline frames (`_timeline_frames`: source frames × timeline fps / clip fps, exact with `Fraction`) and uses that length in both overlap checks. A length that isn't whole (e.g. 24 fps on 60) is checked rounded up, with a warning that Resolve may round it by a frame. An unknown clip rate keeps the source length, with a warning. Preview rows give `frames` in timeline frames, plus `source_frames`, and `clip_fps` when the rate differs. The read-back counts a clip only when its length matches too (within a frame when not whole), so a clip placed at another length is `partial`. The schema text and AGENTS.md say the length is converted. The fake's `append_clips` now converts lengths like Resolve (`conform_fps`).

**Verified 2026-11-26 (unit):** `tests/unit/test_timeline_steps.py` `PlaceClipsAtAnotherRate`, 30 fps clips on a 60 fps timeline: preview lengths; an item only the converted length reaches is refused; clips of one call overlapping only when converted are refused (the later one after and before the earlier); back to back at the converted length placed and read back; a clip Resolve places unconverted is `partial`; 24 fps on 60 is checked as 63 frames, with a warning; the same rate is unchanged. Six of the seven failed before the fix; the back-to-back one passed before too. Each of six breaks is caught: the timeline check, the same-call check or the planned end unconverted, `floor` for `ceil`, no length in the read-back, no one-frame tolerance. Full suite and `tests/smoke_bridge.py` pass.

**Verified 2026-11-26 (live)**, after restarting the MCP server, on a scratch timeline "I-30 live check" (60 fps) in "LiL - dev log 01": a 60 fps anchor clip at +90; "Wet, wet everywhere.mp4" (30 fps), source 0-60, at +0 is `blocked` ("would overwrite Little moment 001.mkv on V1 at 01:00:01:30"; it passed before the fix); at +300 the preview gives `frames: 120`, `source_frames: 60`, `clip_fps: 30`, and the confirm is `success`, read back as 120 frames (216300-216420); two such clips of one call at +600 and +660 are `blocked` as overlapping. The scratch timeline was then deleted.

<a id="i-31"></a>
### I-31 `add_transition` skips the audio crossfade without a warning when nothing is linked (low)

**Where:** `resolve_editor/tools/clips.py` (`_linked_audio`)

**Problem:** the matching audio crossfade (I-07) goes only on audio that Resolve lists as linked to the video clip. When the video clip has no linked items, `_linked_audio` returns no audio and no note. The result is `success` with no `linked` rows and no warning, even when audio from the same file sits on A1 at the same cut. The other skip cases (linked audio not at the cut, `include_linked=false`) do warn.

**Live 2026-11-26** ("Dev Log 01"): Cross Dissolve at the end of "2026-11-22 17-08-51.mkv" on V1, whose audio on A1 isn't linked to it. Video transition `success`, no warning, A1 kept a hard cut. A second call on the audio item added the crossfade. The newly placed clips, which are linked, got their crossfade as expected.

**Found** by reading the timeline back after the transition.

<a id="i-32"></a>
### I-32 `batch` refuses tool names with the `edit__` prefix, and its error doesn't say so (low)

**Where:** `resolve_editor/dispatch.py` (`batch`, the check that refuses "unknown or nested tools")

**Problem:** a batch step's `tool` must be the bare handler name (`add_transition`). The agent sees the tools as `edit__add_transition`, and AGENTS.md and the batch schema say "run several `edit__` tools" without naming the form a step needs. A step named `edit__add_transition` is refused as unknown: `blocked`, "unknown or nested tools: ['edit__add_transition', ...]". The message reads as if the tool can't be batched, not that the name is wrong.

**Live 2026-11-26** ("Dev Log 01"): 8 steps named `edit__add_transition` in one batch preview were refused. I took it to mean `add_transition` can't be batched and added them one by one, which left 9 "Dev Log 01 before transition ..." backups where one batch would have made one.

**Found** while adding transitions at 8 cuts; the cause found by reading `batch` afterwards (`add_transition` is in `HANDLERS` and `PREVIEWABLE`).

**Fix idea:** accept the `edit__` prefix in a step's `tool` (strip it), and name the expected form in the schema and in the error.

## Code review fixes

Found 2026-11-24 in a review of the Python code against common practice, not by testing in Resolve. All are known by **Code**, then reproduced by a unit test that failed before the fix. Numbered C-xx, apart from the I-xx list.

### C-01 The stdio servers depend on PYTHONUTF8 (medium, fixed)

**Where:** `resolve_editor/servers/gateway.py` and `legacy.py` (`main`)

**Problem:** both servers read stdin and write stdout in the locale's encoding (cp1250 on a Polish Windows). Only `PYTHONUTF8=1` in the client config made them UTF-8. Without it, the legacy server garbled non-ASCII arguments (caption text) or crashed on bytes the code page doesn't define, and the gateway could fail to write a reply with `ensure_ascii=False`: the error was caught and logged, the request got no answer and the client waited.

**Fix:** new `resolve_editor/servers/stdio.py` `use_utf8()`, called first in both `main()`s, reconfigures stdin and stdout to UTF-8.

**Verified:** `tests/unit/test_stdio.py` `StdioServer`, servers started with `PYTHONIOENCODING=cp1252`, `PYTHONUTF8=0`, sending "Zażółć Łódź 日本語" (`Ł` is C5 81 in UTF-8, and 0x81 is undefined in cp1252, so it can't survive a wrong decode by chance).

### C-02 One bad line stops the legacy server (medium, fixed)

**Where:** `resolve_editor/servers/legacy.py` (`main`)

**Problem:** `json.loads` ran outside any `try`, and only `LookupError` from `handle` was caught. A malformed line or any other exception ended the process, and every later `legacy__` call failed with "not running".

**Fix:** a line that isn't a JSON object gets a JSON-RPC parse error (`-32700`, id null); another exception gets `-32000` with its message, like the gateway. The server keeps reading.

**Verified:** `tests/unit/test_stdio.py` `test_legacy_keeps_answering_after_bad_input`.

### C-03 Closing a child server leaks its pipes (low, fixed)

**Where:** `resolve_editor/servers/child.py` (`Child.close`); `tests/unit/test_bridge_lock.py` (`BridgeLock.child`)

**Problem:** `close` never closed the child's stdin and stdout, caught any `Exception` instead of `subprocess.TimeoutExpired`, and didn't wait for the process after `kill()`. The bridge-lock test's child processes had the same leak and no encoding. The test run showed five `ResourceWarning`s for unclosed pipes.

**Fix:** `close` terminates, waits, kills and waits on timeout, joins the reader thread and closes both pipes; a second call is harmless. The test closes its pipes after the process has ended and reads them as UTF-8.

**Verified:** `tests/unit/test_stdio.py` `ChildClose`; `python -W error::ResourceWarning -m unittest` passes.

### C-04 One corrupt line breaks `audit_log` (low, fixed)

**Where:** `resolve_editor/tools/diagnostics.py` (`audit_log`)

**Problem:** every line was parsed with `json.loads`, so one corrupt line (e.g. cut short by a crash mid-write) made `edit__audit_log` raise and show nothing.

**Fix:** a line that can't be parsed is returned as `{"unreadable": <line>}`; the others are returned as before.

**Verified:** `tests/unit/test_delivery.py` `test_a_corrupt_line_is_reported_not_raised`.

### C-05 `snapshot_timeline` has an unreachable `partial` result (low, fixed)

**Where:** `resolve_editor/timeline.py` (`snapshot_timeline`)

**Problem:** it raises when the check fails, so the following `"success" if ok else "partial"` could only ever be `success`. Dead code, misleading about what the function returns.

**Fix:** the check raises; otherwise the result is `success`. No change in behaviour.

### C-06 A missing argument fails with a bare `KeyError` (low, fixed)

**Where:** `resolve_editor/dispatch.py` (`run`)

**Problem:** the tools index their arguments directly, and nothing checked them against the `required` lists in `schemas/edit.py`. A call without a required argument reached the model as `KeyError: 'item_ids'`, not saying it was an argument or which tool needs it. A batch step without one failed the same way in the preview.

**Fix:** `run` first checks the schema's required top-level arguments; a missing one, or one that is null, is `blocked` with "missing argument(s): enabled" before Resolve is called. Batch steps go through `run`, so the preview reports it per step. Fields inside arrays (`clips[].record`, `markers[].name`) are not checked.

Alongside, two checks against drift, neither a bug so far: `outcome.op` takes a `Status` literal, so mypy reports a misspelled status, and `tests/unit/test_dispatch.py` `ToolLists` fails when `READ_ONLY`, `PREVIEWABLE`, `CONFIRMABLE` or `TIMELINE_READS` names a tool that doesn't exist, or a tool and its schema don't match.

**Verified:** `tests/unit/test_dispatch.py` `RequiredArguments`, failing before the fix with the `KeyError`s; every `SAMPLE_ARGS` entry passes. A status typo put into `tools/audio.py` was reported by mypy, and a misspelled `TIMELINE_READS` entry failed `ToolLists`; both were reverted.

### C-07 A child server that dies mid-call hangs the gateway for up to 30 minutes (medium, fixed)

**Where:** `resolve_editor/servers/child.py` (`Child.request`, `_read_responses`)

**Problem:** when a child server (the legacy bridge server or the upstream engine) exited while handling a request, the reader thread stopped, but `request` kept waiting for a reply until its timeout: 1800 s for `tools/call`. The client saw nothing for half an hour. Found while mapping untested code with coverage.

**Fix:** when the child's output ends, the reader marks the child as exited and puts a marker on the reply queue. A waiting `request` raises "<label> exited while handling <method>" at once, and later requests raise "not running" at once. The gateway turns both into an error reply. A dead child is not restarted: the client reconnects (`/mcp`).

**Verified:** `tests/unit/test_stdio.py` `test_a_child_that_exits_mid_call_fails_the_call_at_once`, which waited out its 20 s timeout before the fix.

### C-08 The gateway doesn't answer a line that isn't a JSON object (low, fixed)

**Where:** `resolve_editor/servers/gateway.py` (`main`); `legacy.py` (`main`)

**Problem:** a line that wasn't valid JSON, or was JSON but not an object (e.g. an array), was only logged to stderr, and the client got no reply. JSON-RPC answers these with an error and id null. The legacy server answered both (C-02), but gave a non-object the parse error code.

**Fix:** both servers answer a line that doesn't parse with `-32700` (parse error) and valid JSON that isn't an object with `-32600` (invalid request), id null, and keep reading.

**Verified:** `tests/unit/test_gateway_routing.py` `test_bad_input_gets_an_error_reply_and_the_gateway_goes_on` and `LegacyMain`, both failing before the fix.

## Live tests

### Setup

Timeline `Transition test`, one 1080p60 H.264/AAC recording (2275 frames) used twice:

| Clip | Timeline | Source frames | Tracks |
|---|---|---|---|
| A | 01:00:00:00-01:00:05:00 | 180-480 | V1 + A1, linked |
| B | 01:00:05:00-01:00:10:00 | 1500-1800 | V1 + A1, linked |

Both have plenty of spare frames on each side.

### Status

| Test | What | Status | Related |
|---|---|---|---|
| T1 | Centered 60-frame Cross Dissolve | **Pass** | I-07 (fixed), I-10 (fixed) |
| T2 | Left/right alignment, start/end position | **Pass** (span rule recorded) | I-04 |
| T3 | Cut without spare frames | **Run**: refusal rule recorded | I-09 (fixed) |
| T4 | Misspelled name, zero length, longer than the clip | **Run** (zero length blocked since I-08) | I-04, I-08, I-09 (fixed) |
| T5a | Audio `Cross Fade +3 dB` | **Read-back pass**; not listened to or restart-tested | I-07 (fixed) |
| T5b | Other simple, audio and Fusion types (no OFX: Studio dialog risk) | Not run | I-04 |
| T6 | Same transition added twice | Not run | |
| T7 | Transition on a single Text+ edge | Not run | |
| T8 | Persistence after a Resolve restart | **Pass for T1 only**; repeat after T2-T7 | |

### T1 Cross Dissolve: pass

- Call on A's video item: `type: "Cross Dissolve"`, `category: "simple"`, `position: "end"`,
  `alignment: "center"`, `duration: 60`.
- Read back on V1 at 01:00:04:30-01:00:05:30, 60 frames. All four clip items kept id, position and source start.
- `timeline_summary` counted 1 transition, with no false gaps or overlaps.
- Exported frames: 04:29 only A, 04:45 mostly A, 05:00 even mix, 05:15 mostly B, 05:30 only B.
- Not checked: playback and final render.

### T2 Alignment and position: pass

- 2026-11-23, one scratch timeline per case, set up as above (cut at +300). Cross Dissolve, `position` end on A and start on B, `alignment` left, center and right, `duration` 30 and 31: 12 cases.
- Span relative to the cut, the same for both positions: left `-d..0`, center `-ceil(d/2)..+floor(d/2)` (30: -15..15, 31: -16..15), right `0..+d`.
- `GetProperty()` on each transition gave the requested `TransitionType`, `TransitionCategory`, `TransitionAlignment` and `TransitionDuration`. All clips kept position and source start.
- Not checked: exported frames, playback.

### T3 No spare frames: run 2026-11-23

Video-only clips cut at 300 (60 fps, 2275-frame source), raw `AddTransition` at the outgoing clip's end, 60-frame Cross Dissolve unless noted.

| Unused source frames | Alignment | Result |
|---|---|---|
| plenty both sides | center | made, 270-330 |
| none after the outgoing clip | center / left / right | refused / made 240-300 / refused |
| none before the incoming clip | center / left / right | refused / made 240-300 / made 300-360 |
| none on either side | center | refused |
| 10 on each side | center 60, 20, 21 | all made 290-310 (shortened to 20) |
| 10 on each side | left 20 / right 20 | made 290-300 / 300-310 (shortened to 10) |

### T4 Bad requests: run 2026-11-23

Same setup, plenty of spare frames: "Cross Disolve" refused; an audio type (`Cross Fade +3 dB`, category audio) on video refused; Cross Dissolve with category `fusion` made a normal Cross Dissolve; 1000 frames on 300-frame clips made 0-600. Zero length is blocked before Resolve since I-08.

### T5a Audio crossfade: read-back pass

- Call on A's audio item: `type: "Cross Fade +3 dB"`, `category: "audio"`, otherwise as T1.
- Read back on A1 at the same span. Clips and video dissolve unchanged; summary counted 2 transitions.
- Not checked: the sound. Play 01:00:03:00-01:00:07:00; expect a smooth drop (source averages about -27 dB before
  and -34 dB after) with no click or step at 01:00:05:00.

### T8 Restart: pass for T1

- After a restart: same transition id, type and span, and same clip items.
- The exported frame at 01:00:05:00 was byte-identical to the one from before the restart.
- No fade handle had been dragged on these clips, so this case doesn't share the `SetFades` persistence bug
  described in `README.md`.
- The audio crossfade was added after this restart, so it isn't covered.

### F1 Script fades on video and audio clips: lost on restart (2026-11-25)

The `SetFades` persistence bug in `README.md` ("Known Resolve bug") was only seen on Text+ titles before. Same bug on normal clips, free Resolve 21.2.0.6:

- Scratch timeline `_RCE_fade_test`, one linked V1 + A1 clip (1080p60 recording, source frames 600-1200). `edit__set_fades` set 60-frame fade-in and fade-out on both; read-back `passed`. No fade handle dragged by hand.
- Saved, quit and restarted Resolve: all four fades read back 0, and the user saw none in the timeline.
- Control, same restart: timeline `Dev Log 01`, separate V1 video and A1 audio clips of the same file. The user dragged a fade-in on each by hand, then `edit__set_fades` set both to 60 frames. Both still 60 after the restart.

So the workaround (drag a fade handle once per clip) applies to video and audio clips too.

## Open observation

A backup made with `edit__snapshot_timeline` before adding a track reported success, but was no longer in
`legacy__list_timelines` later in the session. It may have been deleted by hand or not saved. Not counted as a
bug until that is known.

## After fixing

- From the repo root: `python -m unittest` (baseline: 141 tests, all pass) and `python tests/smoke_bridge.py`
  (needs `lupa`).
- Restart the MCP server, and the bridge if the Lua changed, then repeat the affected live tests.
- Update the transitions row in `README.md`, plus `AGENTS.md` and `PATCH_NOTES.md`.
