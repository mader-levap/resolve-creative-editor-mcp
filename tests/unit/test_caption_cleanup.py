"""Removing captions with their own timelines, and deleting caption timelines nothing uses."""
from tests.support import READ_OPS, Base, FakeResolve, item

from resolve_editor import dispatch

ONE = "T 1123-120000 caption 0001"  # on T in two parts
TWO = "T 1123-120000 caption 0002"
ORPHAN = "Old 1101-000000 caption 0001"  # on no timeline
ELSEWHERE = "Other 1101-000000 caption 0002"  # placed on another timeline only


def project():
    """Clip a on V1; caption ONE (parts p1, p2) and TWO (q1) on V2; two more caption timelines in the project."""
    f = FakeResolve([item("a", 1000, 300), item("p1", 1100, 30, name=ONE, track=2),
                     item("p2", 1130, 20, name=ONE, track=2), item("q1", 1200, 30, name=TWO, track=2)])
    f.caption_text = {ONE: "first", TWO: "second", ORPHAN: "old", ELSEWHERE: "other"}
    f.timelines[:] = ["T", ONE, TWO, ORPHAN, ELSEWHERE, "Other"]
    f.other_usage = {ELSEWHERE: ["Other"]}
    f.orphans = []
    return f


def writes(f):
    return [op for op in f.calls if op not in READ_OPS]


class RemoveCaptions(Base):
    """edit__remove_captions: every part off the track. By default with a backup, which still places the caption
    timelines, so they stay (live 2026-11-25: deleting one left the backup's clip Media Offline); with
    delete_timelines=true no backup, and caption timelines nothing else places are deleted too."""

    def remove(self, f, **args):
        self.use(f)
        return dispatch.run("remove_captions", {"confirm": True, "timeline": "T", **args})

    def test_preview_names_parts_and_timelines_and_changes_nothing(self):
        f = self.use(project())
        r = dispatch.run("remove_captions", {"captions": [1], "delete_timelines": True})
        self.assertEqual(r["_operation"]["status"], "preview", r)
        row = r["plan"]["captions"][0]
        self.assertEqual((row["text"], row["parts"], row["in"]), ("first", 2, "00:00:36:20"))
        self.assertEqual(r["plan"]["timelines_deleted"], [ONE])
        self.assertTrue(any("no backup" in w for w in r["_operation"]["warnings"]), r)
        self.assertEqual(r["timeline"], "T")
        self.assertEqual(writes(f), [])

    def test_default_backs_up_and_keeps_the_timelines(self):
        f = project()
        preview = self.remove(f, captions=[1], confirm=False)
        self.assertEqual(preview["plan"]["timelines_deleted"], [])
        self.assertTrue(any("delete_unused_captions" in w for w in preview["_operation"]["warnings"]), preview)
        r = self.remove(f, captions=[1])
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(r["_operation"]["changes"], {"captions_removed": 1, "parts_deleted": 2,
                                                      "timelines_deleted": 0})
        self.assertEqual([x["id"] for x in f.items], ["a", "q1"])
        self.assertEqual(f.items[1]["start"], 1200)  # no ripple
        self.assertEqual(f.calls.count("duplicate_timeline"), 1)
        self.assertNotIn("delete_timeline", f.calls)

    def test_delete_timelines_deletes_them_without_a_backup(self):
        f = project()
        r = self.remove(f, captions=[1], delete_timelines=True)
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(r["_operation"]["changes"], {"captions_removed": 1, "parts_deleted": 2,
                                                      "timelines_deleted": 1})
        self.assertEqual(f.deleted_timelines, [ONE])
        self.assertNotIn("duplicate_timeline", f.calls)
        self.assertLess(f.calls.index("delete_items"), f.calls.index("delete_timeline"))

    def test_by_part_id_and_several_at_once(self):
        f = project()
        r = self.remove(f, captions=["p2", 2], delete_timelines=True)
        self.assertEqual(r["_operation"]["changes"]["captions_removed"], 2, r)
        self.assertEqual([x["id"] for x in f.items], ["a"])
        self.assertEqual(sorted(f.deleted_timelines), [ONE, TWO])

    def test_a_timeline_still_placed_elsewhere_is_kept_and_named(self):
        f = project()
        f.other_usage[ONE] = ["T before batch 20261125-120000"]  # e.g. an older backup
        r = self.remove(f, captions=[1], delete_timelines=True)
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(f.deleted_timelines, [])
        self.assertEqual(r["kept"], [{"name": ONE, "used_by": ["T before batch 20261125-120000"]}])

    def test_a_copy_left_on_this_timeline_keeps_the_timeline(self):
        f = project()
        f.items.append(item("copy", 1500, 30, name=ONE, track=3))
        r = self.remove(f, captions=["p1"], delete_timelines=True)
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertIn("copy", [x["id"] for x in f.items])
        self.assertEqual(f.deleted_timelines, [])
        self.assertEqual(r["kept"], [{"name": ONE, "used_by": ["T"]}])

    def test_unknown_caption_is_refused(self):
        for key in (7, "nope"):
            with self.subTest(key=key):
                f = self.use(project())
                r = dispatch.run("remove_captions", {"captions": [key]})
                self.assertEqual(r["_operation"]["status"], "blocked", r)
                self.assertIn(str(key), r["reason"])
                self.assertEqual(writes(f), [])

    def test_no_captions_given_is_refused(self):
        self.use(project())
        self.assertEqual(dispatch.run("remove_captions", {"captions": []})["_operation"]["status"], "blocked")


class DeleteUnusedCaptions(Base):
    """edit__delete_unused_captions: caption timelines no timeline places, project-wide."""

    def test_preview_lists_only_the_unused_and_changes_nothing(self):
        f = self.use(project())
        r = dispatch.run("delete_unused_captions", {})
        self.assertEqual(r["_operation"]["status"], "preview", r)
        self.assertEqual((r["plan"]["count"], r["plan"]["timelines"]), (1, [ORPHAN]))
        self.assertEqual(writes(f), [])

    def test_confirm_deletes_them(self):
        f = self.use(project())
        r = dispatch.run("delete_unused_captions", {"confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(r["_operation"]["changes"], {"timelines_deleted": 1})
        self.assertEqual(f.deleted_timelines, [ORPHAN])
        self.assertIn(ONE, f.timelines)

    def test_nothing_unused(self):
        f = project()
        f.timelines.remove(ORPHAN)
        self.use(f)
        self.assertEqual(dispatch.run("delete_unused_captions", {})["plan"]["count"], 0)
        r = dispatch.run("delete_unused_captions", {"confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["changes"], {"timelines_deleted": 0}, r)
        self.assertNotIn("delete_timeline", f.calls)
