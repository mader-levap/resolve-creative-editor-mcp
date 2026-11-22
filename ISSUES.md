# Issues

Found while testing `edit__add_transition`, 2026-11-22. This is the base for fixes; nothing here is fixed yet.

- Environment: free DaVinci Resolve 21.2.0.6, Windows 10, 60 fps timeline.
- Code: branch `fix/issues`, `1a58791` **plus uncommitted changes**, so line numbers refer to that working tree.

How each item is known:

- **Live**: seen in Resolve.
- **Fake**: reproduced with the real Python code against `FakeResolve` from `tests/test_editor_tools.py`, extended
  with the missing bridge ops. This proves our logic is wrong, not how Resolve reacts.
- **Code**: found by reading the code, not run.

## Summary

| ID | Severity | Issue | Known by |
|---|---|---|---|
| [I-01](#i-01) | **Critical** | `batch` preview makes real changes | Fake |
| [I-02](#i-02) | High | An error inside `batch` loses the results and backup name | Fake |
| [I-03](#i-03) | High | `batch` continues after a `partial` step | Fake |
| [I-04](#i-04) | High | `add_transition` verifies only the length | Fake |
| [I-05](#i-05) | Medium | `ripple_trim` ignores transitions on other tracks | Fake |
| [I-06](#i-06) | Medium | `add_transition` has no preview, backup or timeline-switch guard | Fake, code |
| [I-07](#i-07) | Medium | Linked audio keeps a hard cut, without a warning | Live |
| [I-08](#i-08) | Medium | Zero and negative durations aren't rejected | Fake |
| [I-09](#i-09) | Low | Every refusal blames spare source frames | Code |
| [I-10](#i-10) | Low | `at` in the transition result is ambiguous | Live |
| [I-11](#i-11) | Low | `timeline_summary` hides empty tracks | Live, fake |
| [I-12](#i-12) | Low | The live transition test accepts a refusal as a pass | Code |

Suggested order: I-01, then I-02 and I-03, then the `add_transition` group (I-04, I-06 to I-10), then the rest.
**Until I-01 is fixed, use `edit__batch` only with tools that have their own preview.**

## Issues

<a id="i-01"></a>
### I-01 `batch` preview makes real changes (critical)

**Where:** `editor_tools.py:996`

**Problem:** without `confirm`, `batch` builds its preview by calling `run()` on every step. Tools with no confirm
check of their own execute immediately, with no backup, while the batch reports `preview`. Confirming then runs
them a second time.

| Tool in a batch preview | Result |
|---|---|
| `add_transition`, `set_fades`, `set_audio`, `set_enabled`, `add_markers`, `snapshot_timeline` | Writes (reproduced) |
| `add_audio_markers` (without `dry_run`), `export_srt`, `export_timeline` | Writes (code) |
| `move_item` | Correct, no write (reproduced) |

**Repro:** `run("batch", {"operations": [{"tool": "add_transition", "args": {"item_id": "a"}}]})`. The bridge
receives `add_transition`. After repeating with `confirm`, the calls are
`add_transition, duplicate_timeline, add_transition`, so even the backup contains the unapproved change.

`CLAUDE.md` and the server instructions both recommend `batch`, so this is easy to hit. The existing
`test_batch_previews_without_writing` only covers `move_item`, which is why it passes.

**Fix:** only call handlers known to support preview. For the others, describe the step without running it. Make
this an allow-list, so that new tools are safe by default.

**Done when:** a test loops over every entry in `HANDLERS` and proves that a batch preview makes no bridge write,
file write or audit entry.

<a id="i-02"></a>
### I-02 An error inside `batch` loses the results and backup name (high)

**Where:** `editor_tools.py:990` (`batch`), `editor_tools.py:1020` (`run`)

**Problem:** `_b()` raises on a bridge error and `batch` doesn't catch it. The caller gets only the error: not the
completed steps and not the name of the backup that was made. The failed batch isn't written to the audit log.

**Repro:** confirmed batch whose `add_transition` is refused. The backup is created, then a bare `RuntimeError`
is raised and the audit log stays empty.

**Fix:** catch per step, record it as `failed` with the reason, stop, and return `results` and `snapshot`.

**Done when:** a refusal at step 2 of 3 returns step 1, the failure and the backup name; step 3 doesn't run; the
batch is audited.

<a id="i-03"></a>
### I-03 `batch` continues after a `partial` step (high)

**Where:** `editor_tools.py:1004`

**Problem:** it stops only on `failed` and `blocked`. `partial` is what tools return when verification fails, so
later steps run on a timeline that isn't in the expected state.

**Repro:** a transition returns the wrong length (`partial`); the following `set_enabled` still runs.

**Fix:** also stop on `partial`.

**Done when:** no step runs after a `partial` one.

<a id="i-04"></a>
### I-04 `add_transition` verifies only the length (high)

**Where:** `editor_tools.py:686`

**Problem:** type, category, position, alignment and track are never compared with the request. With no
`duration`, nothing is compared and the result is still `passed`.

**Repro:** request Cross Dissolve at the end of an item at frame 1000; the fake returns `Wipe` at frame 1. The
result is `success` / `passed`.

**Fix:** re-read the timeline and check that the transition exists on the item's track, at the span implied by
position, alignment and length, and that neighbouring clips didn't change. Resolve documents read-only
`TransitionType` and `TransitionCategory`, and `TransitionAlignment`, through `GetProperty`; try those. Report
`unverified` for anything that can't be checked.

**Done when:** a wrong type, track or span gives `partial` / `contradiction`.

<a id="i-05"></a>
### I-05 `ripple_trim` ignores transitions on other tracks (medium)

**Where:** `editor_tools.py:582`

**Problem:** transitions block a trim only on the same video track. On audio or other video tracks they skip the
overlap check completely, although ripple delete shifts all tracks.

**Repro:** item 1000-1100, trim 30, transition at 1080-1120. On V1 it is blocked; on A1 or V2 it previews as OK.
What Resolve then does to that transition is untested.

**Fix:** apply the removed-range overlap check to transitions on other tracks.

**Done when:** the A1 and V2 cases are blocked.

<a id="i-06"></a>
### I-06 `add_transition` has no preview, backup or timeline-switch guard (medium)

**Where:** `editor_tools.py:686`, `editor_tools.py:1022`

**Problem:** it writes on the first call and takes no backup. `run()` only guards against Resolve switching
timelines when `confirm` is set, which this tool never receives when called directly. There is also no tool made
for removing or changing a transition, and whether `legacy__delete_items` can remove one is untested.

**Fix:** add `confirm` with a preview (item, cut, expected span, available spare frames) and `backup` (default
true), like move and trim.

**Done when:** no write without `confirm`, a backup is returned, and the guard runs.

<a id="i-07"></a>
### I-07 Linked audio keeps a hard cut, without a warning (medium)

**Where:** `editor_tools.py:686`

**Problem:** a transition on a video item lands only on the video track. In test T1, A1 kept a hard cut under a
1 s dissolve and `warnings` was empty.

**Workaround:** call again on the audio item's id with `category: "audio"`, `type: "Cross Fade +3 dB"` and the
same position, alignment and length (test T5a).

**Fix:** add `include_linked` to create the matching audio crossfade. Without it, warn. Report clearly if only one
of the two succeeds.

**Done when:** one call can create both, and a video-only call on linked clips warns.

<a id="i-08"></a>
### I-08 Zero and negative durations aren't rejected (medium)

**Where:** `editor_tools.py:686`

**Problem:** `if a.get("duration")` treats 0 as "not given", so Resolve picks a length and the result is
`passed`. Negative values are sent to Resolve unchanged.

**Repro:** with 0 the options sent have no `duration`; with -5 they contain `-5`.

**Fix:** omitted or null means automatic; anything else must be a positive integer, otherwise `blocked`.

**Done when:** 0 and -5 are blocked without a bridge write.

<a id="i-09"></a>
### I-09 Every refusal blames spare source frames (low)

**Where:** `resolve_bridge.lua:856`

**Problem:** `AddTransition` returns nil without a reason and the bridge always suggests missing spare frames. A
misspelled name, wrong category or unsupported item would get the same hint.

**Fix:** include the requested options and list the possible causes. Mention spare frames as the cause only after
checking them.

**Done when:** the message doesn't point to one unverified cause. T3 and T4 will show the real behaviour.

<a id="i-10"></a>
### I-10 `at` in the transition result is ambiguous (low)

**Where:** `editor_tools.py:694`

**Problem:** `at` is where the transition starts (01:00:04:30 in T1) and is easily read as the cut (01:00:05:00).

**Fix:** return `start`, `end` and `cut`.

**Done when:** all three are in the result.

<a id="i-11"></a>
### I-11 `timeline_summary` hides empty tracks (low)

**Where:** `editor_tools.py:252` (`analyze`), `editor_tools.py:280`

**Problem:** tracks are derived from items. After `legacy__add_track` returned a count of 3, the summary still
listed only V1 and V2, so a new track can't be verified or seen.

**Fix:** read track counts from Resolve (`GetTrackCount`) and list empty tracks with 0.

**Done when:** a new empty V3 shows as `"V3": 0`.

<a id="i-12"></a>
### I-12 The live transition test accepts a refusal as a pass (low)

**Where:** `tests/live_resolve.py:99`

**Problem:** the check passes on `success`, `partial` or any result containing "refused". The unit tests have no
`add_transition` test at all.

**Fix:** live-test a cut with spare frames (must succeed with the exact span) and one without (record and assert
the real behaviour) separately. Add `add_transition` to `FakeResolve` with tests for the issues above.

**Done when:** the live test fails if a valid transition is refused or misplaced.

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
| T1 | Centered 60-frame Cross Dissolve | **Pass** | I-07, I-10 |
| T2 | Left/right alignment, start/end position | Not run | I-04 |
| T3 | Cut without spare frames | Not run | I-09 |
| T4 | Misspelled name, zero length, longer than the clip | Not run | I-04, I-08, I-09 |
| T5a | Audio `Cross Fade +3 dB` | **Read-back pass**; not listened to or restart-tested | I-07 |
| T5b | Other simple, audio and Fusion types (no OFX: Studio dialog risk) | Not run | I-04 |
| T6 | Same transition added twice | Not run | I-01 (effect of the double run) |
| T7 | Transition on a single Text+ edge | Not run | |
| T8 | Persistence after a Resolve restart | **Pass for T1 only**; repeat after T2-T7 | |

### T1 Cross Dissolve: pass

- Call on A's video item: `type: "Cross Dissolve"`, `category: "simple"`, `position: "end"`,
  `alignment: "center"`, `duration: 60`.
- Read back on V1 at 01:00:04:30-01:00:05:30, 60 frames. All four clip items kept id, position and source start.
- `timeline_summary` counted 1 transition, with no false gaps or overlaps.
- Exported frames: 04:29 only A, 04:45 mostly A, 05:00 even mix, 05:15 mostly B, 05:30 only B.
- Not checked: playback and final render.

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

## Open observation

A backup made with `edit__snapshot_timeline` before adding a track reported success, but was no longer in
`legacy__list_timelines` later in the session. It may have been deleted by hand or not saved. Not counted as a
bug until that is known.

## After fixing

- `python -m unittest tests.test_editor_tools` (baseline on 2026-11-22: 32 tests, all pass).
- Restart the MCP server, and the bridge if the Lua changed, then repeat the affected live tests.
- Update the transitions row in `README.md`, plus `AGENTS.md` and `PATCH_NOTES.md`.
