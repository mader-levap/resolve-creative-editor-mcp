# Issues

Found while testing `edit__add_transition`, 2026-11-22. This is the base for fixes. Fixed so far: I-01, I-13, I-16.

- Environment: free DaVinci Resolve 21.2.0.6, Windows 10, 60 fps timeline.
- Code: branch `fix/issues`. Line numbers are as of the I-16 fix.

How each item is known:

- **Live**: seen in Resolve.
- **Fake**: reproduced with the real Python code against `FakeResolve` from `tests/test_editor_tools.py`, extended
  with the missing bridge ops. This proves our logic is wrong, not how Resolve reacts.
- **Code**: found by reading the code, not run.

## Summary

| ID | Severity | Issue | Known by |
|---|---|---|---|
| [I-01](#i-01) | ~~Critical~~ **Fixed** | `batch` preview makes real changes | Fake, live |
| [I-02](#i-02) | High | An error inside `batch` loses the results and backup name | Fake |
| [I-03](#i-03) | High | `batch` continues after a `partial` step | Fake |
| [I-04](#i-04) | High | `add_transition` verifies only the length | Fake |
| [I-05](#i-05) | Medium | `ripple_trim` ignores transitions on other tracks | Fake |
| [I-06](#i-06) | Medium | `add_transition` has no preview or backup | Fake, code |
| [I-07](#i-07) | Medium | Linked audio keeps a hard cut, without a warning | Live |
| [I-08](#i-08) | Medium | Zero and negative durations aren't rejected | Fake |
| [I-09](#i-09) | Low | Every refusal blames spare source frames | Code |
| [I-10](#i-10) | Low | `at` in the transition result is ambiguous | Live |
| [I-11](#i-11) | Low | `timeline_summary` hides empty tracks | Live, fake |
| [I-12](#i-12) | Low | The live transition test accepts a refusal as a pass | Code |
| [I-13](#i-13) | ~~Critical~~ **Fixed** | Bridge replies fail when half-written or over 65 KB | Live, fake |
| [I-14](#i-14) | Low | The gateway test writes to the real audit log | Live |
| [I-15](#i-15) | High | Two clients sharing the bridge lose or drop requests and replies | Live, fake, code |
| [I-16](#i-16) | ~~Critical~~ **Fixed** | Edits and backups can hit the wrong timeline | Live, fake |
| [I-17](#i-17) | High | A confirm isn't tied to the previewed timeline | Code |
| [I-18](#i-18) | Medium | `batch` reports `passed` for unverified steps | Fake |
| [I-19](#i-19) | Medium | Markers without a name are never added | Live |

Order, one fix at a time, worst first: I-03, I-17, I-02, I-15, I-04, then medium, then low. Re-rank after each fix.

## Issues

<a id="i-01"></a>
### I-01 `batch` preview makes real changes (critical, fixed)

**Where:** `editor_tools.py` (`batch`, `_preview_step`, `run`)

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
- Live on a scratch timeline, calling `editor_tools` from Python: previews left items, settings, markers, timelines,
  files and the audit log unchanged; a confirmed batch made one backup without the change and one transition.
- Through MCP after a server restart: a 10-step preview (8 listed, 2 previewed despite an inner `confirm`)
  changed nothing. `confirm` values `"false"`, `"true"`, `"no"` and `1`, sent as raw requests, gave previews only.

**Limits:** a preview checks each step against the current timeline, not the result of earlier steps. Tools without
a preview still write when called directly (I-06).

<a id="i-02"></a>
### I-02 An error inside `batch` loses the results and backup name (high)

**Where:** `editor_tools.py:1007` (`batch`), `editor_tools.py:1042` (`run`)

**Problem:** `_b()` raises on a bridge error and `batch` doesn't catch it. The caller gets only the error: not the
completed steps and not the name of the backup that was made. The failed batch isn't written to the audit log.

**Repro:** confirmed batch whose `add_transition` is refused. The backup is created, then a bare `RuntimeError`
is raised and the audit log stays empty.

**Fix:** catch per step, record it as `failed` with the reason, stop, and return `results` and `snapshot`.

**Done when:** a refusal at step 2 of 3 returns step 1, the failure and the backup name; step 3 doesn't run; the
batch is audited.

<a id="i-03"></a>
### I-03 `batch` continues after a `partial` step (high)

**Where:** `editor_tools.py:1023`

**Problem:** it stops only on `failed` and `blocked`. `partial` is what tools return when verification fails, so
later steps run on a timeline that isn't in the expected state.

**Repro:** a transition returns the wrong length (`partial`); the following `set_enabled` still runs. The same
happens for all 9 tools that can return `partial`. The batch also drops that step's warnings and changes, so the
result doesn't say why it is partial.

**Fix:** also stop on `partial`.

**Done when:** no step runs after a `partial` one.

<a id="i-04"></a>
### I-04 `add_transition` verifies only the length (high)

**Where:** `editor_tools.py:692`

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

**Where:** `editor_tools.py:588`

**Problem:** transitions block a trim only on the same video track. On audio or other video tracks they skip the
overlap check completely, although ripple delete shifts all tracks.

**Repro:** item 1000-1100, trim 30, transition at 1080-1120. On V1 it is blocked; on A1 or V2 it previews as OK.
What Resolve then does to that transition is untested.

**Fix:** apply the removed-range overlap check to transitions on other tracks.

**Done when:** the A1 and V2 cases are blocked.

<a id="i-06"></a>
### I-06 `add_transition` has no preview or backup (medium)

**Where:** `editor_tools.py:692`

**Problem:** it writes on the first call and takes no backup. (The timeline-switch guard it lacked came with
the I-16 fix.) There is also no tool made
for removing or changing a transition, and whether `legacy__delete_items` can remove one is untested.

**Fix:** add `confirm` with a preview (item, cut, expected span, available spare frames) and `backup` (default
true), like move and trim.

**Done when:** no write without `confirm`, and a backup is returned.

<a id="i-07"></a>
### I-07 Linked audio keeps a hard cut, without a warning (medium)

**Where:** `editor_tools.py:692`

**Problem:** a transition on a video item lands only on the video track. In test T1, A1 kept a hard cut under a
1 s dissolve and `warnings` was empty.

**Workaround:** call again on the audio item's id with `category: "audio"`, `type: "Cross Fade +3 dB"` and the
same position, alignment and length (test T5a).

**Fix:** add `include_linked` to create the matching audio crossfade. Without it, warn. Report clearly if only one
of the two succeeds.

**Done when:** one call can create both, and a video-only call on linked clips warns.

<a id="i-08"></a>
### I-08 Zero and negative durations aren't rejected (medium)

**Where:** `editor_tools.py:692`

**Problem:** `if a.get("duration")` treats 0 as "not given", so Resolve picks a length and the result is
`passed`. Negative values are sent to Resolve unchanged.

**Repro:** with 0 the options sent have no `duration`; with -5 they contain `-5`.

**Fix:** omitted or null means automatic; anything else must be a positive integer, otherwise `blocked`.

**Done when:** 0 and -5 are blocked without a bridge write.

<a id="i-09"></a>
### I-09 Every refusal blames spare source frames (low)

**Where:** `resolve_bridge.lua:880`

**Problem:** `AddTransition` returns nil without a reason and the bridge always suggests missing spare frames. A
misspelled name, wrong category or unsupported item would get the same hint.

**Fix:** include the requested options and list the possible causes. Mention spare frames as the cause only after
checking them.

**Done when:** the message doesn't point to one unverified cause. T3 and T4 will show the real behaviour.

<a id="i-10"></a>
### I-10 `at` in the transition result is ambiguous (low)

**Where:** `editor_tools.py:700`

**Problem:** `at` is where the transition starts (01:00:04:30 in T1) and is easily read as the cut (01:00:05:00).

**Fix:** return `start`, `end` and `cut`.

**Done when:** all three are in the result.

<a id="i-11"></a>
### I-11 `timeline_summary` hides empty tracks (low)

**Where:** `editor_tools.py:258` (`analyze`), `editor_tools.py:286`

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

<a id="i-13"></a>
### I-13 Bridge replies fail when half-written or over 65 KB (critical, fixed)

**Where:** `mcp_server.py` (`_read_csv_reply`), Resolve 21.2 transport only

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
- `test_smoke.py` passes (older Fusion.prefs transport).
- Through MCP after a server restart: normal reads work on the restarted server. 70 and 200 KB replies, sent as raw
  requests to a fresh server, arrive exact through both the edit__ and legacy__ routes.

**Limit:** a timeout after a write is still ambiguous in general, so read back before retrying.

<a id="i-14"></a>
### I-14 The gateway test writes to the real audit log (low)

**Where:** `tests/test_gateway.py:7`, and `GatewayResilience` in `tests/test_editor_tools.py` uses the same pattern

**Problem:** `test_gateway` starts the gateway with the user's environment, so the gateway logs the fake
`legacy__hello` call as a successful change in the real `audit.jsonl`, and `edit__audit_log` shows it.

**Workaround:** set `RESOLVE_BRIDGE_DIR` to a temporary folder when running the test.

**Fix:** set it to a temporary folder in the test's environment.

**Done when:** running all tests leaves the real audit log unchanged.

<a id="i-15"></a>
### I-15 Two clients sharing the bridge collide (high)

**Where:** `mcp_server.py:175` (`call_bridge`), `resolve_bridge.lua:21` and `resolve_bridge.lua:24`

**Problem:** every client uses the same `request.lua`, `request.lua.tmp` and reply slot (`reply.csv` on 21.2), with
no lock between processes. A client is any process that calls the bridge: another session's MCP server, or a script
that imports `editor_tools` while the server is in use. A server that gets no Resolve calls doesn't interfere.

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
rename of the request (`mcp_server.py:186-190`), because reading and cleanup catch `OSError`.

**Not affected, by the code:** parallel tool calls in one session. The gateway handles one request at a time and
waits for its legacy child. A bridge call gives up after 120 s, well inside the gateway's 1800 s limit for a
child's tool call.

**Fix:** hold an OS file lock in the bridge folder from writing the request to cleanup (`msvcrt` on Windows, `fcntl`
elsewhere). The OS releases it if the process dies.

- Bound the wait, and then fail with "bridge busy, nothing was sent". `edit__` calls have no gateway timeout, so
  after an unbounded wait a write could run long after the client gave up on the call.
- A unique `.tmp` name alone fixes only 5 and 6.
- Servers started before the fix ignore the lock until restarted.

**Limits of that fix:**

- It serializes single bridge calls, not whole tools. Another client can still edit between a tool's read and
  its write. A timeline switch there is undone by the pin (I-16).
- After a timeout the lock is released while Resolve may still be busy, so the next call can still report "Bridge
  not running".

**Done when:** a test with two processes and a fake bridge loses nothing, a waiter that gives up sends nothing, and
the live two-client run has no failures.

<a id="i-16"></a>
### I-16 Edits and backups can hit the wrong timeline (critical, fixed)

**Where:** `editor_tools.py` (`run`, `_b`), `resolve_bridge.lua` (dispatcher, `add_title_cards`)

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
- `test_smoke.py` runs the pin, its refusals and the title cards on the real Lua.
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
### I-17 A confirm isn't tied to the previewed timeline (high)

**Where:** `editor_tools.py` (`run`, `_cached`)

**Problem:** `confirm=true` edits the timeline that is current at that moment. If the user switched after the
preview, tools that work by position (`place_clips`, markers, captions) apply the approved plan to another timeline.
Reads can also describe the previous timeline for up to 3 s after a switch by hand.

**Fix:** previews return their timeline and the confirm names it, otherwise it is blocked. Don't serve cached reads
across a timeline switch.

**Done when:** a switch between preview and confirm gives no write.

<a id="i-18"></a>
### I-18 `batch` reports `passed` for unverified steps (medium)

**Where:** `editor_tools.py` (`batch`)

**Problem:** verification is derived from the step statuses. A batch with only `copy_grade`, which can't be read
back and returns `unverified`, reports `passed`.

**Fix:** report `unverified` if any successful writing step was.

**Done when:** that batch reports `unverified`.

<a id="i-19"></a>
### I-19 Markers without a name are never added (medium)

**Where:** `resolve_bridge.lua` (`add_marker`, `add_markers`), `editor_tools.py` (`add_markers`)

**Problem:** Resolve 21.2 refuses `AddMarker` with an empty name, which is the default. `edit__add_markers` then
returns `partial` with "a marker already exists at some of those frames", and `legacy__add_marker` returns
`ok: false`.

**Repro, live:** on a scratch timeline at free frames, three unnamed markers through `add_markers` and one through
`add_marker` were refused. Named ones were added.

**Fix:** default to a non-empty name and correct the warning. Check whether `copy_settings` fails the same way for
unnamed clip markers (not run).

**Done when:** a marker without a name is added by both tools.

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

- `python -m unittest tests.test_editor_tools` (baseline after the I-16 fix: 56 tests, all pass).
- Restart the MCP server, and the bridge if the Lua changed, then repeat the affected live tests.
- Update the transitions row in `README.md`, plus `AGENTS.md` and `PATCH_NOTES.md`.
