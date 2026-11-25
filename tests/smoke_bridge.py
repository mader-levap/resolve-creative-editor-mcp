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
-- A Media Pool folder tree: Footage/Day 1 holds a clip and a timeline, Edits holds the timeline WORK, two bins are
-- named Dup. Like Resolve, every call hands out a new proxy object, so folders must be compared by GetUniqueId.
local ids = 0
local function newfolder(name, parent)
  ids = ids + 1
  local f = {name=name, subs={}, clips={}, parent=parent, id="f" .. ids}
  if parent then table.insert(parent.subs, f) end
  return f
end
local function proxy(f)
  if not f then return nil end
  return {f=f, GetName=function() return f.name end, GetUniqueId=function() return f.id end,
    GetClipList=function() return f.clips end,
    GetSubFolderList=function() local out = {}; for i, x in ipairs(f.subs) do out[i] = proxy(x) end; return out end}
end
local function tl_clip(name)
  return {GetMediaId=function() return "tl-" .. name end, GetName=function() return name end,
    GetClipProperty=function() return {Type="Timeline"} end,
    GetTimeline=function() return {GetName=function() return name end} end}
end
local root = newfolder("Master")
root.clips = {clip}
local footage = newfolder("Footage", root)
local day1 = newfolder("Day 1", footage)
day1.clips = {{GetMediaId=function() return "id2" end, GetName=function() return "b.mp4" end,
  GetClipProperty=function() return {Frames="10", FPS="24"} end}, tl_clip("_RCE_INNER")}
local edits = newfolder("Edits", root)
edits.clips = {tl_clip("WORK")}
newfolder("Dup", root); newfolder("Dup", root)
local current_folder = root
local made = {}
local placed = {GetUniqueId=function() return "item1" end, GetName=function() return "placed" end,
  GetStart=function() return 0 end, GetEnd=function() return 10 end, GetDuration=function() return 10 end,
  -- clip markers count from the source start (live, docs/ISSUES.md I-23); 21.2 refuses an empty name (I-19)
  GetMarkers=function() return {[348]={name="Marker 1", color="Blue"}, [5]={name="early", color="Red"},
    [2000]={name="", color="Green"}} end,
  AddMarker=function(self, f, color, name) if name == "" then return false end; clip_marker(f, name); return true end,
  AddTransition=function() return nil end}  -- Resolve gives no reason (live T3/T4, docs/ISSUES.md I-09)
-- a placed caption: its media pool item is the caption's own timeline, whose V1 title holds the text
-- its Text+ inputs: a number, a point (Fusion adds a third value), a FuID, an image (not copied) and a keyframed one
local caption_values = {StyledText="line one\nline two", Size=0.034, Center={0.5, 0.08, 0}, Font="Normograf",
  Image1="img", Thickness2=0.05}
local caption_types = {StyledText="Text", Size="Number", Center="Point", Font="Text", Image1="Image",
  Thickness2="Number"}
local function caption_input(id)
  return {GetAttrs=function() return {INPS_ID=id, INPS_DataType=caption_types[id]} end,
    GetConnectedOutput=function() if id == "Thickness2" then return {} end end}
end
local caption_tool = {GetInput=function(self, k) return caption_values[k] end,
  SetInput=function(self, k, v) text_input_set(k, v) end,
  GetInputList=function() local out = {}
    for _, id in ipairs({"StyledText", "Size", "Center", "Font", "Image1", "Thickness2"}) do
      out[#out + 1] = caption_input(id) end
    return out end}
local caption_title = {GetFusionCompByIndex=function() return {FindToolByID=function() return caption_tool end} end}
placed.GetMediaPoolItem = function() return {GetTimeline=function()
  return {GetName=function() return "_RCE_FULL 1125-000000 caption 0001" end,
    GetItemListInTrack=function(self, kind, i) if kind == "video" and i == 1 then return {caption_title} end
    return {} end} end} end
local function timeline(name)
  if not made[name] then
    local tool = {SetInput=function() end}
    local title = {GetFusionCompByIndex=function() return {FindToolByID=function() return tool end} end,
      GetDuration=function() return title_len() end}
    made[name] = {GetName=function() return name end,
      GetSetting=function(self, k) return setting(name, k) end,
      SetSetting=function(self, k, v) return set_setting(name, k, v) end,
      GetTrackCount=function() return 1 end,
      GetItemListInTrack=function(self, kind)
        if kind == "video" and (name == "_RCE_FULL" or name == "_RCE_FULL_TOO") then return {placed} end
        if kind == "video" and name:match(" caption %d%d%d%d$") and not name:match("^_RCE_NOTEXT") then
          return {caption_title} end
        return {} end,
      GetStartFrame=function() return 0 end,
      GetEndFrame=function() return 100 end, GetCurrentTimecode=function() return "01:00:00:00" end,
      GetMediaPoolItem=function() return {} end,
      AddMarker=function() wrote("marker", current()); return true end,
      InsertFusionTitleIntoTimeline=function() wrote("title", current()); return title end}
  end
  return made[name]
end
local pool = {GetRootFolder=function() return proxy(root) end,
  AddSubFolder=function(self, parent, name)
    if name == "_RCE_RENAMED" then name = "_RCE_RENAMED 1" end  -- Resolve picking another name
    current_folder = parent.f  -- Resolve may make the parent current; create_bin must undo it
    return proxy(newfolder(name, parent.f))
  end,
  GetCurrentFolder=function() return proxy(current_folder) end,
  SetCurrentFolder=function(self, f) current_folder = f.f; return true end,
  DeleteFolders=function(self, list)
    for _, f in ipairs(list) do
      local subs = f.f.parent.subs
      for i, x in ipairs(subs) do if x == f.f then table.remove(subs, i); break end end
      folder_deleted(f.f.name)
    end
    current_folder = root  -- like Resolve: deleting a bin makes the root current
    return true
  end,
  DeleteTimelines=function(self, list) for _, t in ipairs(list) do tl_deleted(t:GetName()) end; return true end,
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
world: dict[str, Any] = {"project": "demo", "names": [], "cur": None, "wrote": [], "ignore": {}, "deleted": [],
                         "text_inputs": []}


def lupa_table(v):
    """Whether v is a Lua table handed to Python."""
    return lua_mod.lua_type(v) == "table"
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
    g.folder_deleted = lambda name: world["deleted"].append(("bin", name))
    g.tl_deleted = lambda name: world["deleted"].append(("timeline", name))
    # Text+ SetInput calls, converted here (in the bridge thread, which holds the Lua runtime)
    g.text_input_set = lambda k, v: world["text_inputs"].append((k, list(v.values()) if lupa_table(v) else v))
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

# A request pinned to a timeline runs there or not at all (docs/ISSUES.md I-16). Real Lua, real call_bridge.
os.environ.update(RESOLVE_BRIDGE_DIR=bridge_dir, RESOLVE_FUSION_PREFS=prefs)
from resolve_editor import bridge  # noqa: E402  (after the environment above is set)

MARKER = {"frame": 5, "name": "m"}
PIN = {"project": "demo", "name": "WORK"}


def reset(cur="OTHER", project="demo", names=("WORK", "OTHER"), ignore=None):
    world.update(project=project, names=list(names), cur=cur, wrote=[], ignore=ignore or {})


reset()
r = bridge.call_bridge("get_state", {})
assert r["ok"] and r["result"]["pins"] is True and r["result"]["named_markers"] is True, r
# The new copy names where the one before it stopped, and records its own stages (docs/ISSUES.md I-22)
assert r["result"]["stage_marker"] is True, r
assert r["result"]["track_counts"] == {"video": 1, "audio": 1}, r  # empty tracks show in the summary (I-11)
assert r["result"]["previous_run_stuck"] == {"op": "get_state", "phase": "op", "at": 1795900318}, r
assert data["claude_bridge_stage"].split()[1:3] == ["idle", "-"], data["claude_bridge_stage"]
# Resolve 21.2 refuses markers without a name: the bridge says so and writes none of them (docs/ISSUES.md I-19)
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

# A refused transition names what was asked and the causes seen live, without picking one (docs/ISSUES.md I-09)
r = bridge.call_bridge("add_transition", {"item_id": "item1", "options": {
    "type": "Cross Disolve", "category": "simple", "position": "end", "alignment": "center", "duration": 30}})
assert not r["ok"] and r["error"].startswith("Resolve refused the transition"), r
for part in ("Cross Disolve", "center", "30", "doesn't know", "unused source frames"):
    assert part in r["error"], (part, r)
assert "may have no spare" not in r["error"], r

# Caption text is read through the caption's own timeline; an unknown item gives an error, not a failed call
r = bridge.call_bridge("caption_texts", {"item_ids": ["item1", "nope"]})
assert r["ok"] and r["result"]["item1"] == {"text": "line one\nline two"}, r
assert "not found" in r["result"]["nope"]["error"], r

# read_titles reads a caption's Text+ through its own timeline: copyable inputs only, keyframed ones listed
r = bridge.call_bridge("read_titles", {"item_ids": ["item1", "nope"]})
assert r["ok"], r
got = r["result"]["item1"]
assert got["kind"] == "caption" and got["animated"] == ["Thickness2"], got
assert got["inputs"] == {"StyledText": "line one\nline two", "Size": 0.034, "Center": [0.5, 0.08],
                         "Font": "Normograf"}, got
assert "not found" in r["result"]["nope"]["error"], r

# style_text_plus reaches a caption's Text+ too; Enabled* goes first, a point is sent as {x, y}, StyledText and
# inputs that already have the value (Size) are skipped
r = bridge.call_bridge("style_text_plus", {"item_ids": ["item1"], "inputs": {"Thickness2": 0.06, "Enabled2": 1,
                                           "Center": [0.4, 0.1], "Font": "Arial", "StyledText": "no",
                                           "Size": 0.034}})
assert r["ok"] and r["result"]["styled"] == 1, r
sets = world["text_inputs"]
assert [k for k, _ in sets] == ["Enabled2", "Center", "Font", "Thickness2"], sets
assert sets[1][1] == [0.4, 0.1], sets


# delete_timeline: by exact name; refuses the current timeline and unknown names before deleting anything;
# with_captions also deletes the caption timelines placed on it, unless another timeline still uses them
CAP = "_RCE_FULL 1125-000000 caption 0001"
for names, why in ((["WORK"], "current"), (["_RCE_FULL", "nope"], "no timeline named nope"), ([], "name")):
    reset(cur="WORK", names=("WORK", "_RCE_FULL", CAP))
    world["deleted"].clear()
    r = bridge.call_bridge("delete_timeline", {"names": names})
    assert not r["ok"] and why in r["error"] and world["deleted"] == [], (names, r, world["deleted"])
reset(cur="WORK", names=("WORK", "_RCE_FULL", CAP))
world["deleted"].clear()
r = bridge.call_bridge("delete_timeline", {"names": ["_RCE_FULL"]})
assert r["ok"] and r["result"]["deleted"] == ["_RCE_FULL"] and r["result"]["captions_deleted"] == [], r
assert world["deleted"] == [("timeline", "_RCE_FULL")], world["deleted"]
world["deleted"].clear()
r = bridge.call_bridge("delete_timeline", {"names": ["_RCE_FULL"], "with_captions": True})
assert r["ok"] and r["result"]["captions_deleted"] == [CAP], r
assert world["deleted"] == [("timeline", "_RCE_FULL"), ("timeline", CAP)], world["deleted"]
reset(cur="WORK", names=("WORK", "_RCE_FULL", "_RCE_FULL_TOO", CAP))
world["deleted"].clear()
r = bridge.call_bridge("delete_timeline", {"names": ["_RCE_FULL"], "with_captions": True})
assert r["ok"] and r["result"]["captions_deleted"] == [], r
assert r["result"]["captions_kept"] == [{"name": CAP, "used_by": "_RCE_FULL_TOO"}], r
assert world["deleted"] == [("timeline", "_RCE_FULL")], world["deleted"]
world["deleted"].clear()
r = bridge.call_bridge("delete_timeline", {"names": ["_RCE_FULL", "_RCE_FULL_TOO"], "with_captions": True})
assert r["ok"] and r["result"]["captions_deleted"] == [CAP], r


# caption_usage: caption timelines (by name, with a Text+ on V1) and the timelines that place each one
ORPHAN = "_RCE_OLD 1125-000000 caption 0002"
reset(cur="WORK", names=("WORK", "_RCE_FULL", "_RCE_FULL_TOO", CAP, ORPHAN, "_RCE_NOTEXT caption 0003"))
r = bridge.call_bridge("caption_usage", {})
assert r["ok"] and r["result"]["captions"] == [CAP, ORPHAN], r
assert r["result"]["used_by"] == {CAP: ["_RCE_FULL", "_RCE_FULL_TOO"]}, r


# Bins by path from the Media Pool root ("" is the root); every refusal changes nothing
def call(op, **a):
    return bridge.call_bridge(op, a)


def current_bin():
    return call("get_state")["result"]["current_bin"]


reset(cur="WORK", names=("WORK", "OTHER"))
world["deleted"].clear()
assert current_bin() == "", current_bin()
r = call("create_bin", bin="Footage/_RCE_NEW")
assert r["ok"] and r["result"] == {"bin": "Footage/_RCE_NEW"} and current_bin() == "", r
for path, why in (("Footage/_RCE_NEW", "already"), ("Nope/_RCE_X", "no bin Nope"), ("", "root"), ("/", "root"),
                 ("Dup/_RCE_X", "ambiguous")):
    r = call("create_bin", bin=path)
    assert not r["ok"] and why in r["error"], (path, r)
r = call("create_bin", bin="_RCE_RENAMED")
assert not r["ok"] and "_RCE_RENAMED 1" in r["error"] and ("bin", "_RCE_RENAMED 1") in world["deleted"], r
assert current_bin() == "", current_bin()
r = call("use_bin", bin="Footage/Day 1")
assert r["ok"] and r["result"] == {"bin": "Footage/Day 1", "previous": ""} and current_bin() == "Footage/Day 1", r
r = call("use_bin", bin="/Footage/_RCE_NEW/")  # slashes at the ends are ignored
assert r["ok"] and r["result"] == {"bin": "Footage/_RCE_NEW", "previous": "Footage/Day 1"}, r
assert not call("use_bin", bin="Footage/Nope")["ok"] and current_bin() == "Footage/_RCE_NEW"
world["deleted"].clear()
for path, why in (("", "root"), ("Footage/_RCE_NEW", "current bin"), ("Footage", "current bin"),
                 ("Edits", "current timeline"), ("Dup", "ambiguous"), ("Nope", "no bin")):
    r = call("delete_bin", bin=path, with_contents=True)
    assert not r["ok"] and why in r["error"], (path, r)
call("use_bin", bin="")
r = call("delete_bin", bin="Footage")
assert not r["ok"] and "with_contents" in r["error"] and "2 bins, 1 clip, 1 timeline" in r["error"], r
assert world["deleted"] == [], world["deleted"]
call("use_bin", bin="Edits")
r = call("delete_bin", bin="Footage/_RCE_NEW")  # empty: no with_contents needed
assert current_bin() == "Edits", current_bin()  # the current bin stays current
assert r["ok"] and r["result"] == {"bin": "Footage/_RCE_NEW", "bins": 0, "clips": 0, "timelines": 0}, r
r = call("delete_bin", bin="Footage", with_contents=True)
assert r["ok"] and r["result"] == {"bin": "Footage", "bins": 1, "clips": 1, "timelines": 1}, r
assert world["deleted"] == [("bin", "_RCE_NEW"), ("timeline", "_RCE_INNER"), ("bin", "Footage")], world["deleted"]
assert not call("use_bin", bin="Footage")["ok"]

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
