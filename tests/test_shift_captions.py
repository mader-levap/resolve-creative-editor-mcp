"""Finding captions by their text and moving them, by default with every caption after them."""
from tests.support import Base, FakeResolve, item

from resolve_editor import dispatch

T = "T 1123-120000 caption "  # caption timelines are named "<timeline> <stamp> caption NNNN"


def captions(*specs, track=2):
    """specs: (number, [(start, frames), ...], text); more than one (start, frames) is a caption placed in parts."""
    f = FakeResolve([item("v", 1000, 2000, name="clip.mp4", track=1)])  # a video clip that must never move
    n = 0
    for num, where, text in specs:
        name = f"{T}{num:04d}"
        f.timelines.append(name)
        f.caption_text[name] = text
        for start, frames in where:
            n += 1
            it = item(f"c{n}", start, frames, name=name, track=track)
            f.items.append(it)
            f.settings[it["id"]] = {"properties": {"ZoomX": 1}, "fades": {"FadeIn": 6, "FadeOut": 6}, "color": "",
                                    "enabled": True, "speed": {"Percentage": 100}, "linked": [], "fusion_comps": 0,
                                    "takes": 0, "media_id": f"tl-{name}", "markers": {}}
    return f


FOUR = ((1, [(1000, 60)], "first"), (2, [(1100, 60)], "second line"), (3, [(1200, 300), (1500, 100)], "long one"),
        (4, [(1700, 60)], "last"))


def starts(f, track=2):
    return sorted((x["name"][-4:], x["start"]) for x in f.items if x["track"] == track)


class ListCaptions(Base):
    def test_rows_group_parts_and_carry_text(self):
        self.use(captions(*FOUR))
        r = dispatch.run("list_captions", {})
        self.assertEqual(r["count"], 4)
        self.assertEqual([c["n"] for c in r["captions"]], [1, 2, 3, 4])
        long = r["captions"][2]
        self.assertEqual((long["text"], long["frames"], len(long["ids"])), ("long one", 400, 2))
        self.assertEqual((long["in"], long["out"]), ("00:00:40:00", "00:00:53:10"))  # 1200 and 1600 at 30 fps
        self.assertEqual(long["track"], "V2")
        self.assertNotIn("clip.mp4", [c["name"] for c in r["captions"]])

    def test_filters(self):
        self.use(captions(*FOUR))
        self.assertEqual([c["n"] for c in dispatch.run("list_captions", {"text": "LINE"})["captions"]], [2])
        r = dispatch.run("list_captions", {"start": 1150, "end": 1250})
        self.assertEqual([c["n"] for c in r["captions"]], [2, 3])
        self.assertEqual(dispatch.run("list_captions", {"track_index": 3})["count"], 0)


class ShiftCaptions(Base):
    def shift(self, f, **a):
        self.use(f)
        preview = dispatch.run("shift_captions", a)
        if preview["_operation"]["status"] != "preview":
            return preview
        self.assertEqual(f.calls.count("append_clips"), 0)  # a preview changes nothing
        return dispatch.run("shift_captions", {**a, "confirm": True, "timeline": preview["timeline"]})

    def test_moves_the_caption_and_every_later_one_by_default(self):
        f = captions(*FOUR)
        r = self.shift(f, caption=2, seconds=3)  # 90 frames at 30 fps
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(starts(f), [("0001", 1000), ("0002", 1190), ("0003", 1290), ("0003", 1590), ("0004", 1790)])
        self.assertEqual(starts(f, track=1), [(".mp4", 1000)])  # other tracks stay
        self.assertEqual(f.calls.count("duplicate_timeline"), 1)  # one backup for the whole move
        self.assertEqual([c["n"] for c in r["captions"]], [2, 3, 4])

    def test_only_the_caption_without_following(self):
        f = captions(*FOUR)
        r = self.shift(f, caption=4, seconds=1, following=False)
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(starts(f)[-1], ("0004", 1730))
        self.assertEqual(starts(f)[:2], [("0001", 1000), ("0002", 1100)])

    def test_a_caption_in_parts_moves_whole_by_any_part(self):
        f = captions(*FOUR)
        r = self.shift(f, caption="c4", frames=-20, following=False)  # c4 is the second part of caption 3
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual([s for s in starts(f) if s[0] == "0003"], [("0003", 1180), ("0003", 1480)])

    def test_refusals(self):
        cases = [({"caption": 2, "seconds": -2}, "first"),                        # lands on caption 1
                 ({"caption": 2, "frames": 50, "following": False}, "long one"),  # lands on caption 3
                 ({"caption": 1, "frames": -1500}, "timeline start")]
        for args, why in cases:
            with self.subTest(args=args):
                f = captions(*FOUR)
                r = self.shift(f, **args)
                self.assertEqual(r["_operation"]["status"], "blocked", r)
                self.assertIn(why, r["reason"])
                self.assertEqual(f.calls.count("append_clips"), 0)

    def test_a_collision_suggests_following(self):
        r = self.shift(captions(*FOUR), caption=2, frames=50, following=False)
        self.assertIn("following", r["reason"])

    def test_bad_arguments(self):
        self.use(captions(*FOUR))
        for args, why in (({"caption": 2}, "seconds or frames"),
                          ({"caption": 2, "seconds": 1, "frames": 3}, "seconds or frames"),
                          ({"caption": 9, "seconds": 1}, "no caption 9"),
                          ({"caption": "v", "seconds": 1}, "not a caption"),
                          ({"caption": 2, "frames": 0}, "nothing")):
            with self.subTest(args=args):
                r = dispatch.run("shift_captions", args)
                self.assertEqual(r["_operation"]["status"], "blocked", r)
                self.assertIn(why, r["reason"])

    def test_seconds_round_to_frames(self):
        f = captions(*FOUR)
        self.shift(f, caption=4, seconds=0.51, following=False)  # 15.3 frames at 30 fps
        self.assertEqual(starts(f)[-1], ("0004", 1715))

    def test_preview_rows(self):
        self.use(captions(*FOUR))
        r = dispatch.run("shift_captions", {"caption": 3, "seconds": 1})
        rows = r["plan"]["captions"]
        self.assertEqual([(x["n"], x["text"]) for x in rows], [(3, "long one"), (4, "last")])
        self.assertEqual((rows[0]["from"], rows[0]["to"]), ("00:00:40:00", "00:00:41:00"))

    def test_captions_on_other_tracks_stay(self):
        f = captions(*FOUR)
        other = captions((9, [(1800, 60)], "other track"), track=3)
        f.items += [x for x in other.items if x["track"] == 3]
        f.settings.update({k: v for k, v in other.settings.items() if k != "v"})
        f.timelines += other.timelines[1:]
        f.caption_text.update(other.caption_text)
        r = self.shift(f, caption=2, seconds=1)
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(starts(f, track=3), [("0009", 1800)])

    def test_a_caption_not_where_expected_after_the_move_is_partial(self):
        class Drifts(FakeResolve):  # Resolve leaving a moved caption a frame off, seen only when read back
            def __call__(self, op, args, **kw):
                if op == "delete_empty_track":
                    moved = [x for x in self.items if x["track"] == 2 and x["id"].startswith("n")]
                    moved[0]["start"] += 1
                    moved[0]["end"] += 1
                return super().__call__(op, args, **kw)
        f = captions(*FOUR)
        d = Drifts(f.items)
        d.settings, d.timelines, d.caption_text = f.settings, f.timelines, f.caption_text
        r = self.shift(d, caption=4, seconds=1, following=False)
        self.assertEqual(r["_operation"]["status"], "partial", r)
        self.assertIn("captions 4", " ".join(r["_operation"]["warnings"]))
