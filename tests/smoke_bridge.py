"""Smoke test: fake `resolve` (Lua) -> real resolve_bridge.lua -> real mcp_server.py over stdio.

Needs `pip install lupa` (a Lua runtime for Python). Run: python tests/smoke_bridge.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

try:
    import lupa.luajit21 as lua_mod  # Resolve uses LuaJIT; fall back to plain Lua
except ImportError:
    import lupa as lua_mod

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo root
sys.path.insert(0, here)
tmp = tempfile.mkdtemp()
bridge_dir = os.path.join(tmp, "resolve-claude-bridge")
os.makedirs(bridge_dir)

FAKE = r"""
local clip = {GetMediaId=function() return "id1" end, GetName=function() return "a.mp4" end,
  GetClipProperty=function() return {Frames="240", FPS="24", ["File Path"]="C:\\v\\a.mp4"} end}
local folder = {GetClipList=function() return {clip} end, GetSubFolderList=function() return {} end}
local made = {}
local placed = {GetUniqueId=function() return "item1" end, GetName=function() return "placed" end,
  GetStart=function() return 0 end, GetEnd=function() return 10 end, GetDuration=function() return 10 end,
  -- clip markers count from the source start (live, ISSUES.md I-23); 21.2 refuses an empty name (I-19)
  GetMarkers=function() return {[348]={name="Marker 1", color="Blue"}, [5]={name="early", color="Red"},
    [2000]={name="", color="Green"}} end,
  AddMarker=function(self, f, color, name) if name == "" then return false end; clip_marker(f, name); return true end,
  AddTransition=function() return nil end}  -- Resolve gives no reason (live T3/T4, ISSUES.md I-09)
local function timeline(name)
  if not made[name] then
    local tool = {SetInput=function() end}
    local title = {GetFusionCompByIndex=function() return {FindToolByID=function() return tool end} end,
      GetDuration=function() return title_len() end}
    made[name] = {GetName=function() return name end,
      GetSetting=function(self, k) return setting(name, k) end,
      SetSetting=function(self, k, v) return set_setting(name, k, v) end,
      GetTrackCount=function() return 1 end,
      GetItemListInTrack=function() if name == "_RCE_FULL" then return {placed} end return {} end,
      GetStartFrame=function() return 0 end,
      GetEndFrame=function() return 100 end, GetCurrentTimecode=function() return "01:00:00:00" end,
      GetMediaPoolItem=function() return {} end,
      AddMarker=function() wrote("marker", current()); return true end,
      InsertFusionTitleIntoTimeline=function() wrote("title", current()); return title end}
  end
  return made[name]
end
local pool = {GetRootFolder=function() return folder end,
  AddSubFolder=function() return folder end, GetCurrentFolder=function() return folder end,
  SetCurrentFolder=function() return true end,
  CreateEmptyTimeline=function(self, name) created(name); return timeline(name) end,
  AppendToTimeline=function(self, list)
    record(list[1].startFrame, list[1].endFrame); wrote("append", current())
    part(list[1].recordFrame, list[1].startFrame, list[1].endFrame); return {placed}
  end}
local proj = {GetName=function() return project_name() end,
  GetCurrentTimeline=function() local n = current(); if n then return timeline(n) end end,
  GetTimelineCount=function() return count() end,
  GetTimelineByIndex=function(self, i) return timeline(name_at(i)) end,
  SetCurrentTimeline=function(self, t) return switch(t:GetName()) end,
  GetMediaPool=function() return pool end}
resolve = {GetVersionString=function() return "21.1-fake" end, GetCurrentPage=function() return "edit" end,
  GetProjectManager=function() return {GetCurrentProject=function() return proj end} end}
"""

L: dict[str, Any] = {}
appended: list[tuple[int, int]] = []
clip_marks: list[tuple[int, str]] = []
world: dict[str, Any] = {"project": "demo", "names": [], "cur": None, "wrote": [], "ignore": {}}
titles: dict[str, Any] = {"length": 300, "settings": {}, "stuck": False, "parts": []}


def setting(name, key):
    return titles["settings"].get((name, key), "30")


def set_setting(name, key, value):
    if titles["stuck"]:  # Resolve refusing to change it
        return False
    titles["settings"][(name, key)] = value
    return True


def created(name):  # Resolve makes a new timeline current
    world["names"].append(name)
    world["cur"] = name


def switch(name):
    if world["ignore"].get(name, 0):  # Resolve not staying where it was told
        world["ignore"][name] -= 1
    else:
        world["cur"] = name
    return True


prefs = os.path.join(tmp, "Fusion.prefs")
data = {}


def save_prefs(*_):  # mimic Fusion: writes every SetData value into the prefs file
    with open(prefs, "w", encoding="utf-8") as f:
        f.write("{\n" + "".join(f'  {k} = "{v}",\n' for k, v in data.items() if v is not None) + "}\n")


def run_bridge():
    lua = lua_mod.LuaRuntime()
    L["lua"] = lua
    g = lua.globals()
    g.BRIDGE_DIR = bridge_dir + "\\"
    g.record = lambda s, e: appended.append((s, e))
    g.clip_marker = lambda f, name: clip_marks.append((int(f), name))
    g.wrote = lambda what, at: world["wrote"].append((what, at))
    g.current = lambda: world["cur"]
    g.project_name = lambda: world["project"]
    g.count = lambda: len(world["names"])
    g.name_at = lambda i: world["names"][int(i) - 1]
    g.created, g.switch = created, switch
    g.title_len = lambda: titles["length"]
    g.setting, g.set_setting = setting, set_setting
    g.part = lambda rec, s, e: titles["parts"].append((rec, s, e))
    # mimic Resolve's sandbox: no io/require; loadfile reads, fusion prefs is the only writer
    lua.execute("io = nil; require = nil; bmd = {}; fusion = {}")
    g.bmd.wait = time.sleep
    g.fusion.SetData = lambda self, k, v: data.__setitem__(k, v)
    g.fusion.GetData = lambda self, k: data.get(k)
    g.fusion.SavePrefs = save_prefs
    lua.execute(FAKE)
    lua.execute(open(os.path.join(here, "resolve_bridge.lua"), encoding="utf-8").read())


data["claude_bridge_stage"] = "oldrun op get_state 1795900318"  # a copy that got stuck in a Resolve call (I-22)
threading.Thread(target=run_bridge, daemon=True).start()
for _ in range(50):
    if "claude_bridge_inst" in data:
        break
    time.sleep(0.1)

env = dict(os.environ, RESOLVE_BRIDGE_DIR=bridge_dir, RESOLVE_FUSION_PREFS=prefs)
p = subprocess.Popen([sys.executable, os.path.join(here, "mcp_server.py")], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, text=True, env=env)


def rpc(i, method, params=None):
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())["result"]


def text(r):
    return r["content"][0]["text"]


assert rpc(1, "initialize")["serverInfo"]["name"] == "davinci-resolve"
assert len(rpc(2, "tools/list")["tools"]) >= 20
r = rpc(3, "tools/call", {"name": "get_state"})
assert not r.get("isError") and json.loads(text(r))["resolve"] == "21.1-fake", r
r = rpc(4, "tools/call", {"name": "list_media"})
media = json.loads(text(r))
assert media[0]["name"] == "a.mp4" and media[0]["path"] == "C:\\v\\a.mp4", r
r = rpc(5, "tools/call", {"name": "append_clips",
                          "arguments": {"clips": [{"clip": "a.mp4", "start_frame": 10, "end_frame": 50}]}})
assert not r.get("isError"), r
assert appended == [(10, 50)], appended
# end_frame is exclusive; the default full-source range must end at the frame count (240),
# not frame count - 1.
r = rpc(10, "tools/call", {"name": "append_clips",
                           "arguments": {"clips": [{"clip": "a.mp4"}]}})
assert not r.get("isError"), r
assert appended[-1] == (0, 240), appended
r = rpc(11, "tools/call", {"name": "append_clips",
                           "arguments": {"clips": [{"clip": "a.mp4", "start_frame": 10, "end_frame": 10}]}})
assert r["isError"] and "exclusive" in text(r), r
r = rpc(6, "tools/call", {"name": "set_item_properties", "arguments": {"item_id": "x", "properties": {"Evil": 1}}})
assert r["isError"] and "not allowed" in text(r), r
r = rpc(8,"tools/call", {"name": "add_marker", "arguments": {"frame": 5, "name": "m"}})
assert r["isError"] and "No current timeline" in text(r), r

# A request pinned to a timeline runs there or not at all (ISSUES.md I-16). Real Lua, real call_bridge.
os.environ.update(RESOLVE_BRIDGE_DIR=bridge_dir, RESOLVE_FUSION_PREFS=prefs)
from resolve_editor import bridge  # noqa: E402  (after the environment above is set)

MARKER = {"frame": 5, "name": "m"}
PIN = {"project": "demo", "name": "WORK"}


def reset(cur="OTHER", project="demo", names=("WORK", "OTHER"), ignore=None):
    world.update(project=project, names=list(names), cur=cur, wrote=[], ignore=ignore or {})


reset()
r = bridge.call_bridge("get_state", {})
assert r["ok"] and r["result"]["pins"] is True and r["result"]["named_markers"] is True, r
# The new copy names where the one before it stopped, and records its own stages (ISSUES.md I-22)
assert r["result"]["stage_marker"] is True, r
assert r["result"]["previous_run_stuck"] == {"op": "get_state", "phase": "op", "at": 1795900318}, r
assert data["claude_bridge_stage"].split()[1:3] == ["idle", "-"], data["claude_bridge_stage"]
# Resolve 21.2 refuses markers without a name: the bridge says so and writes none of them (ISSUES.md I-19)
for op, args in (("add_marker", {"frame": 5}), ("add_marker", {"frame": 5, "name": " "}),
                 ("add_markers", {"markers": [{"frame": 1, "name": "a"}, {"frame": 2}]})):
    reset(cur="WORK")
    r = bridge.call_bridge(op, args)
    assert not r["ok"] and "needs a name" in r["error"] and world["wrote"] == [], (op, r, world)
reset(cur="WORK")
r = bridge.call_bridge("add_markers", {"markers": [{"frame": 1, "name": "a"}, {"frame": 2, "name": "b"}]})
assert r["ok"] and r["result"]["added"] == 2 and world["wrote"] == [("marker", "WORK")] * 2, (r, world)
reset()
r = bridge.call_bridge("add_marker", MARKER)
assert r["ok"] and world["wrote"] == [("marker", "OTHER")] and not r.get("switched_from"), (r, world)  # no pin
reset()
r = bridge.call_bridge("add_marker", MARKER, timeline=PIN)
assert r["ok"] and world["wrote"] == [("marker", "WORK")] and r["switched_from"] == "OTHER", (r, world)
reset(cur="WORK")
r = bridge.call_bridge("add_marker", MARKER, timeline=PIN)
assert r["ok"] and world["wrote"] == [("marker", "WORK")] and not r.get("switched_from"), (r, world)
for case in (dict(project="another", cur="WORK"), dict(names=["OTHER"]), dict(ignore={"WORK": 99})):
    reset(**case)
    r = bridge.call_bridge("add_marker", MARKER, timeline=PIN)
    assert not r["ok"] and "not run" in r["error"] and world["wrote"] == [], (case, r, world)

CARDS = {"folder": "bin", "track_index": 2, "cards": [
    {"name": "card1", "text": "Hi", "frames": 10, "record_frame": 20},
    {"name": "card2", "text": "Yo", "frames": 10, "record_frame": 40}]}
reset(cur="WORK", ignore={"WORK": 1, "card2": 1})
r = bridge.call_bridge("add_title_cards", CARDS, timeline=PIN)
assert r["ok"] and len(r["result"]["placed"]) == 2, (r, world)
assert [w for w in world["wrote"] if w[0] == "append"] == [("append", "WORK")] * 2, world
assert [w for w in world["wrote"] if w[0] == "title"] == [("title", "card1"), ("title", "card2")], world
reset(cur="WORK", ignore={"WORK": 99})
r = bridge.call_bridge("add_title_cards", CARDS, timeline=PIN)
assert r["ok"] and r["result"]["error"], r
assert not [w for w in world["wrote"] if w[0] == "append"], world

# I-21: a caption longer than the inserted title is placed in parts, all from its one timeline, at the target's rate
LONG = {"folder": "bin", "track_index": 2, "cards": [
    {"name": "long1", "text": "Hi", "frames": 400, "record_frame": 20},
    {"name": "next1", "text": "Yo", "frames": 50, "record_frame": 430}]}
reset(cur="WORK")
titles.update(length=150, settings={("WORK", "timelineFrameRate"): "24"}, parts=[])
r = bridge.call_bridge("add_title_cards", LONG, timeline=PIN)
assert r["ok"] and not r["result"].get("error"), r
assert titles["parts"] == [(20, 0, 150), (170, 0, 150), (320, 0, 100), (430, 0, 50)], titles["parts"]
assert [p["card"] for p in r["result"]["placed"]] == [1, 1, 1, 2], r
assert [w for w in world["wrote"] if w[0] == "title"] == [("title", "long1"), ("title", "next1")], world
assert titles["settings"][("long1", "timelineFrameRate")] == "24", titles
assert titles["settings"][("long1", "useCustomSettings")] == "1", titles
reset(cur="WORK")
titles.update(settings={("WORK", "timelineFrameRate"): "24"}, parts=[], stuck=True)
r = bridge.call_bridge("add_title_cards", LONG, timeline=PIN)
assert r["ok"] and "24" in r["result"]["error"] and titles["parts"] == [], r
titles.update(stuck=False, settings={}, length=300)
r = bridge.call_bridge("get_state", {})
assert r["ok"] and r["result"]["caption_parts"] is True, r

# Clip markers are copied at their own (source) frames, none skipped, an unnamed one named Marker (I-23, I-19)
reset(cur="_RCE_FULL", names=("WORK", "_RCE_FULL"))
r = bridge.call_bridge("copy_settings", {"from_id": "item1", "to_id": "item1", "kind": "audio"})
assert r["ok"] and r["result"]["failed"] == [] and r["result"]["renamed_markers"] == 1, r
assert sorted(clip_marks) == [(5, "early"), (348, "Marker 1"), (2000, "Marker")], clip_marks
r = bridge.call_bridge("get_state", {})
assert r["ok"] and r["result"]["clip_markers_by_source"] is True, r

# A refused transition names what was asked and the causes seen live, without picking one (ISSUES.md I-09)
r = bridge.call_bridge("add_transition", {"item_id": "item1", "options": {
    "type": "Cross Disolve", "category": "simple", "position": "end", "alignment": "center", "duration": 30}})
assert not r["ok"] and r["error"].startswith("Resolve refused the transition"), r
for part in ("Cross Disolve", "center", "30", "doesn't know", "unused source frames"):
    assert part in r["error"], (part, r)
assert "may have no spare" not in r["error"], r

# The scratch-only frame rate helper used by the live tests
reset(cur="WORK", names=("WORK", "_RCE_A", "_RCE_FULL"))
r = bridge.call_bridge("set_scratch_fps", {"timeline": "_RCE_A", "fps": 24})
assert r["ok"] and r["result"]["fps"] == "24", r
for bad in ({"timeline": "WORK", "fps": 24}, {"timeline": "_RCE_FULL", "fps": 24},
            {"timeline": "_RCE_NONE", "fps": 24}):
    r = bridge.call_bridge("set_scratch_fps", bad)
    assert not r["ok"], (bad, r)
titles.update(settings={})

# A stalled op shows in the stage marker while it runs; the stall helper only runs on scratch timelines (I-22)
reset(cur="_RCE_A", names=("WORK", "_RCE_A"))
stalled: dict = {}
caller = threading.Thread(target=lambda: stalled.update(bridge.call_bridge("scratch_stall", {"seconds": 1})))
caller.start()
seen = set()
while caller.is_alive():
    seen.add(" ".join((data.get("claude_bridge_stage") or "").split()[1:3]))
    time.sleep(0.02)
assert stalled.get("ok") and "op scratch_stall" in seen, (stalled, seen)
reset(cur="WORK", names=("WORK", "_RCE_A"))
r = bridge.call_bridge("scratch_stall", {"seconds": 1})
assert not r["ok"] and "_RCE_" in r["error"], r

# A copy replaced while stuck stays silent when it wakes: its late answer would overwrite a newer reply (I-22)
reset(cur="_RCE_A", names=("WORK", "_RCE_A"))
try:
    bridge.call_bridge("scratch_stall", {"seconds": 2}, timeout=0.5, ack_timeout=0.4)
except TimeoutError:
    pass
hang = bridge.read_hang()
assert hang, "the stalled call left no hang record"
late = hang["request"]
before = data["claude_bridge_inst"]
threading.Thread(target=run_bridge, daemon=True).start()
for _ in range(50):
    if data["claude_bridge_inst"] != before:
        break
    time.sleep(0.1)
r = bridge.call_bridge("get_state", {})
assert r["ok"] and r["result"]["previous_run_stuck"]["op"] == "scratch_stall", r
time.sleep(2.5)  # the old copy wakes up
assert bridge.read_reply(late)[0] != late, "the replaced copy answered its stale request"

# A copy taking over after a clean stop or a reload reports nothing stuck
for left in ("x idle - 0", "x reloading - 0"):
    before = data["claude_bridge_inst"]
    data["claude_bridge_stage"] = left
    threading.Thread(target=run_bridge, daemon=True).start()
    for _ in range(50):
        if data["claude_bridge_inst"] != before:
            break
        time.sleep(0.1)
    r = bridge.call_bridge("get_state", {})
    assert r["ok"] and "previous_run_stuck" not in r["result"], (left, r)

data["claude_bridge_inst"] = "other"  # a newer run took over: stops the Lua loop
time.sleep(0.5)
r = rpc(9, "tools/call", {"name": "get_state"})
assert r["isError"] and "not running" in text(r), r
p.terminate()
print("OK using", lua_mod.__name__)
