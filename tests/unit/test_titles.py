"""Text+ titles: reading their text and style, captions in a given style, and turning titles into captions."""
from tests.support import READ_OPS, Base, FakeResolve, item

from resolve_editor import dispatch
from resolve_editor.schemas import edit as schema

HELLO = {"StyledText": "Hello", "Font": "Normograf", "Style": "Regular", "Size": 0.034, "Center": [0.5, 0.08],
         "VerticalTopCenterBottom": 1, "Enabled2": 1, "Thickness2": 0.05, "Red2": 0, "Green2": 0, "Blue2": 0,
         "Alpha2": 1, "Red1": 1, "Green1": 1, "Blue1": 1, "Alpha1": 1}
TITLE = {"StyledText": "Big title", "Font": "Normograf", "Style": "Regular", "Size": 0.06, "Center": [0.5, 0.5]}


def style_only(inputs):
    """The inputs a caption should get: everything but the text, which goes in the card itself."""
    return {k: v for k, v in inputs.items() if k != "StyledText"}


def timeline():
    """Clip a on V1, title hello on V2 (fades 30/15), disabled title big on V3, a transition and a caption."""
    items = [item("a", 1000, 300), item("hello", 1100, 60, name="Text+", track=2),
             item("big", 1000, 90, name="Text+", track=3),
             item("x", 1290, 20, name="Cross Dissolve", type="transition"),
             item("cap", 1200, 30, name="T 1123-120000 caption 0001", track=2)]
    f = FakeResolve(items, details={"hello": {"fades": {"FadeIn": 30, "FadeOut": 15}},
                                    "big": {"fades": {"FadeIn": 0, "FadeOut": 0}, "enabled": False}})
    f.title_inputs = {"hello": dict(HELLO), "big": dict(TITLE)}
    f.caption_text = {"T 1123-120000 caption 0001": "a caption"}
    f.tracks["video"] = 3
    return f


class ReadTitles(Base):
    """edit__read_titles: text and style of plain Text+ titles and of captions."""

    def test_lists_titles_and_captions_but_not_clips_or_transitions(self):
        self.use(timeline())
        r = dispatch.run("read_titles", {})
        self.assertEqual([(t["id"], t["kind"]) for t in r["titles"]], [("big", "title"), ("hello", "title"),
                                                                        ("cap", "caption")])
        self.assertEqual(r["count"], 3)

    def test_reports_text_style_outline_fades_and_state(self):
        self.use(timeline())
        hello = next(t for t in dispatch.run("read_titles", {})["titles"] if t["id"] == "hello")
        self.assertEqual((hello["text"], hello["track"], hello["frames"], hello["enabled"]), ("Hello", "V2", 60, True))
        self.assertEqual(hello["fades"], {"FadeIn": 30, "FadeOut": 15})
        self.assertEqual(hello["style"], {"font": "Normograf", "style": "Regular", "size": 0.034, "x": 0.5, "y": 0.08,
                                       "anchor": "bottom", "line_spacing": None, "color": [1, 1, 1, 1],
                                       "outline": {"thickness": 0.05, "color": [0, 0, 0, 1]}, "box": None})
        self.assertNotIn("inputs", hello)
        big = next(t for t in dispatch.run("read_titles", {})["titles"] if t["id"] == "big")
        self.assertEqual((big["enabled"], big["style"]["anchor"], big["style"]["outline"]), (False, "center", None))

    def test_reports_the_box_and_line_spacing(self):
        f = self.use(timeline())
        f.title_inputs["hello"].update({"Enabled4": 1, "ElementShape4": 2, "Level4": 1, "Red4": 0, "Green4": 0,
                                        "Blue4": 0, "Alpha4": 1, "Opacity4": 0.4, "ExtendHorizontal4": 0.01,
                                        "ExtendVertical4": 0.05, "Round4": 0.15, "LineSpacing": 1.25})
        style = dispatch.run("read_titles", {"item_ids": ["hello"]})["titles"][0]["style"]
        self.assertEqual((style["box"], style["line_spacing"]),
                         ({"per": "line", "opacity": 0.4, "color": [0, 0, 0], "padding": [0.01, 0.05], "round": 0.15},
                          1.25))

    def test_a_box_that_is_off_is_not_reported(self):
        f = self.use(timeline())
        f.title_inputs["hello"].update({"Enabled4": 0, "ElementShape4": 2})
        self.assertIsNone(dispatch.run("read_titles", {"item_ids": ["hello"]})["titles"][0]["style"]["box"])

    def test_all_inputs_gives_the_raw_inputs(self):
        self.use(timeline())
        r = dispatch.run("read_titles", {"item_ids": ["hello"], "all_inputs": True})
        self.assertEqual(r["titles"][0]["inputs"], HELLO)

    def test_range_and_track_filters(self):
        self.use(timeline())
        self.assertEqual([t["id"] for t in dispatch.run("read_titles", {"start": 1095, "end": 1200})["titles"]],
                         ["hello"])
        self.assertEqual([t["id"] for t in dispatch.run("read_titles", {"track_index": 3})["titles"]], ["big"])

    def test_ids_that_are_not_titles_are_named(self):
        self.use(timeline())
        r = dispatch.run("read_titles", {"item_ids": ["hello", "a"]})
        self.assertEqual([t["id"] for t in r["titles"]], ["hello"])
        self.assertEqual([x["id"] for x in r["not_titles"]], ["a"])

    def test_reads_only(self):
        f = self.use(timeline())
        dispatch.run("read_titles", {"all_inputs": True})
        self.assertEqual([op for op in f.calls if op not in READ_OPS], [])


class CaptionStyle(Base):
    """edit__add_captions takes the whole Text+ style: style, x, any input, or every input of another title."""

    def place(self, **extra):
        f = self.use(timeline())
        r = dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "confirm": True,
                                          "timeline": "T", "track_index": 4, **extra})
        self.assertEqual(r["_operation"]["status"], "success", r)
        return f.title_args

    def test_style_x_and_inputs_are_sent(self):
        args = self.place(font="Normograf", style="Regular", size=0.034, x=0.3, y=0.1,
                          inputs={"Enabled2": 1, "Thickness2": 0.05, "Red2": 0})
        self.assertEqual({k: args[k] for k in ("font", "style", "size", "x", "y")},
                         {"font": "Normograf", "style": "Regular", "size": 0.034, "x": 0.3, "y": 0.1})
        self.assertEqual(args["inputs"], {"VerticalTopCenterBottom": 1, "Enabled2": 1, "Thickness2": 0.05, "Red2": 0})

    def test_match_copies_every_input_but_the_text(self):
        self.assertEqual(self.place(match="hello")["inputs"], style_only(HELLO))

    def test_explicit_arguments_win_over_match(self):
        args = self.place(match="hello", size=0.05, y=0.2, inputs={"Thickness2": 0.1})
        self.assertEqual((args["inputs"]["Size"], args["inputs"]["Center"], args["inputs"]["Thickness2"]),
                         (0.05, [0.5, 0.2], 0.1))
        self.assertEqual(args["inputs"]["Font"], "Normograf")

    def test_match_keeps_its_anchor_unless_one_is_given(self):
        self.assertNotIn("VerticalTopCenterBottom", self.place(match="big")["inputs"])
        self.assertEqual(self.place(match="big", anchor="bottom")["inputs"]["VerticalTopCenterBottom"], 1)

    def test_text_in_inputs_is_refused(self):
        self.use(timeline())
        with self.assertRaisesRegex(ValueError, "StyledText"):
            dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}],
                                          "inputs": {"StyledText": "x"}})

    def test_match_must_be_a_title_or_caption(self):
        self.use(timeline())
        with self.assertRaisesRegex(ValueError, "not a Text\\+ title"):
            dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "match": "a"})

    def test_preview_shows_the_style(self):
        self.use(timeline())
        r = dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "match": "hello"})
        self.assertEqual(r["plan"]["style"]["Font"], "Normograf")

    def test_schema_offers_the_style_arguments(self):
        props = next(t for t in schema.TOOLS if t["name"] == "add_captions")["inputSchema"]["properties"]
        for k in ("style", "x", "inputs", "match", "box", "line_spacing"):
            self.assertIn(k, props)


BOX = {"Enabled4": 1, "ElementShape4": 2, "Level4": 1, "Red4": 0.0, "Green4": 0.0, "Blue4": 0.0, "Alpha4": 1,
       "Opacity4": 0.4, "ExtendHorizontal4": 0.01, "ExtendVertical4": 0.05, "Round4": 0.15}


class CaptionBox(Base):
    """edit__add_captions `box` and `line_spacing`: a dark box behind the text, set when the caption is made."""

    def inputs(self, **extra):
        f = self.use(timeline())
        r = dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "confirm": True,
                                          "timeline": "T", "track_index": 4, **extra})
        self.assertEqual(r["_operation"]["status"], "success", r)
        return f.title_args["inputs"]

    def test_true_sends_the_default_box_and_spacing_for_lines(self):
        got = self.inputs(box=True)
        self.assertEqual({k: got[k] for k in BOX}, BOX)
        self.assertEqual(got["LineSpacing"], 1.25)

    def test_an_object_changes_only_what_it_names(self):
        got = self.inputs(box={"opacity": 0.6, "per": "caption", "padding": 0.02, "color": [0.1, 0, 0]})
        self.assertEqual((got["Opacity4"], got["Level4"], got["ExtendHorizontal4"], got["ExtendVertical4"],
                          got["Red4"], got["Round4"]), (0.6, 0, 0.02, 0.02, 0.1, 0.15))
        self.assertNotIn("LineSpacing", got)  # one box around the caption can't overlap itself

    def test_given_spacing_and_raw_inputs_win(self):
        self.assertEqual(self.inputs(box=True, line_spacing=1.1)["LineSpacing"], 1.1)
        self.assertEqual(self.inputs(line_spacing=1.4)["LineSpacing"], 1.4)
        self.assertEqual(self.inputs(box=True, inputs={"Opacity4": 0.8})["Opacity4"], 0.8)

    def test_spacing_from_match_is_kept(self):
        f = self.use(timeline())
        f.title_inputs["hello"]["LineSpacing"] = 1.1
        r = dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "confirm": True,
                                          "timeline": "T", "track_index": 4, "match": "hello", "box": True})
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(f.title_args["inputs"]["LineSpacing"], 1.1)

    def test_false_switches_off_a_box_copied_by_match(self):
        f = self.use(timeline())
        f.title_inputs["hello"].update(BOX)
        dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "confirm": True,
                                      "timeline": "T", "track_index": 4, "match": "hello", "box": False})
        self.assertEqual(f.title_args["inputs"]["Enabled4"], 0)

    def test_preview_shows_the_box_and_a_note(self):
        self.use(timeline())
        r = dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "box": True})
        self.assertEqual(r["plan"]["style"]["Opacity4"], 0.4)
        self.assertTrue(any("bright frame" in w for w in r["_operation"]["warnings"]))

    def test_bad_values_are_refused(self):
        self.use(timeline())
        for box, msg in (({"opacity": 2}, "opacity"), ({"size": 1}, "doesn't know size"),
                         ({"color": [0, 0]}, "color"), ({"per": "word"}, "line or caption"),
                         ({"padding": -0.1}, "padding"), ("yes", "true, false or an object")):
            with self.subTest(box=box), self.assertRaisesRegex(ValueError, msg):
                dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "box": box})
        with self.assertRaisesRegex(ValueError, "line_spacing"):
            dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "line_spacing": 0})


class TitlesToCaptions(Base):
    """edit__titles_to_captions: each title becomes a caption with its text, frames, track, style, fades and state."""

    def confirm(self, f, **extra):
        self.use(f)
        r = dispatch.run("titles_to_captions", {"confirm": True, "timeline": "T", "folder": "_RCE_X", **extra})
        return r

    def test_preview_lists_the_titles_and_changes_nothing(self):
        f = self.use(timeline())
        r = dispatch.run("titles_to_captions", {})
        self.assertEqual(r["_operation"]["status"], "preview", r)
        rows = r["plan"]["titles"]
        self.assertEqual([(x["text"], x["track"], x["frames"]) for x in rows], [("Big title", "V3", 90),
                                                                                 ("Hello", "V2", 60)])
        self.assertEqual(rows[1]["fades"], {"FadeIn": 30, "FadeOut": 15})
        self.assertEqual(r["timeline"], "T")
        self.assertTrue(any("fade" in w for w in r["_operation"]["warnings"]), r)
        self.assertEqual([op for op in f.calls if op not in READ_OPS], [])

    def test_confirm_replaces_each_title_with_its_caption(self):
        f = timeline()
        r = self.confirm(f)
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(r["_operation"]["changes"]["captions_added"], 2)
        self.assertLess(f.calls.index("duplicate_timeline"), f.calls.index("delete_items"))
        self.assertLess(f.calls.index("delete_items"), f.calls.index("add_title_cards"))
        self.assertEqual(f.calls.count("duplicate_timeline"), 1)
        self.assertNotIn("hello", [x["id"] for x in f.items])
        by_track = {c["track_index"]: c["cards"] for c in f.title_calls}
        self.assertEqual(sorted(by_track), [2, 3])
        hello = by_track[2][0]
        self.assertEqual((hello["text"], hello["record_frame"], hello["frames"]), ("Hello", 1100, 60))
        self.assertEqual(hello["inputs"], style_only(HELLO))
        self.assertEqual(by_track[3][0]["inputs"], style_only(TITLE))
        self.assertTrue(all(c["folder"] == "_RCE_X" for c in f.title_calls))

    def test_deletes_without_ripple(self):
        f = timeline()
        before = {x["id"]: x["start"] for x in f.items}
        self.confirm(f)
        self.assertEqual({x["id"]: x["start"] for x in f.items if x["id"] in ("a", "cap")},
                         {"a": before["a"], "cap": before["cap"]})

    def test_fades_and_disabled_state_are_copied(self):
        f = timeline()
        self.confirm(f)
        new = {x["name"]: x["id"] for x in f.items if " caption " in x["name"] and x["id"] != "cap"}
        hello = next(i for n, i in new.items() if f.caption_text[n] == "Hello")
        big = next(i for n, i in new.items() if f.caption_text[n] == "Big title")
        self.assertEqual(f.settings[hello]["fades"], {"FadeIn": 30, "FadeOut": 15})
        self.assertTrue(f.settings[hello]["enabled"])
        self.assertFalse(f.settings[big]["enabled"])

    def test_a_long_title_gets_fade_in_on_its_first_part_and_fade_out_on_its_last(self):
        f = timeline()
        f.title_frames = 40  # the 60-frame title is placed as 40 + 20
        r = self.confirm(f, item_ids=["hello"])
        self.assertEqual(r["_operation"]["status"], "success", r)
        parts = sorted((x for x in f.items if f.caption_text.get(x["name"]) == "Hello"), key=lambda x: x["start"])
        self.assertEqual([x["duration"] for x in parts], [40, 20])
        self.assertEqual([f.settings[x["id"]]["fades"] for x in parts],
                         [{"FadeIn": 30, "FadeOut": 0}, {"FadeIn": 0, "FadeOut": 15}])

    def test_keep_originals_disables_them_and_uses_new_tracks(self):
        f = timeline()
        r = self.confirm(f, keep_originals=True)
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertNotIn("delete_items", f.calls)
        self.assertFalse(f.settings["hello"]["enabled"])
        self.assertEqual(sorted(c["track_index"] for c in f.title_calls), [4, 5])

    def test_refuses_clips_and_captions(self):
        for ids in (["a"], ["cap"], ["hello", "a"]):
            with self.subTest(ids=ids):
                f = self.use(timeline())
                r = dispatch.run("titles_to_captions", {"item_ids": ids})
                self.assertEqual(r["_operation"]["status"], "blocked", r)
                self.assertIn(ids[-1], r["reason"])
                self.assertEqual([op for op in f.calls if op not in READ_OPS], [])

    def test_no_titles_is_refused(self):
        self.use(timeline())
        r = dispatch.run("titles_to_captions", {"track_index": 1})
        self.assertEqual(r["_operation"]["status"], "blocked", r)
        self.assertIn("no plain Text+ titles", r["reason"])

    def test_a_refused_placement_names_what_is_missing_and_the_backup(self):
        f = timeline()
        f.refuse_part = 0  # the first caption (Hello, V2) is refused, so the tool stops before V3
        r = self.confirm(f)
        self.assertEqual(r["_operation"]["status"], "partial", r)
        self.assertIn("Hello", r["reason"])
        self.assertIn("Big title", r["reason"])
        self.assertEqual(len(f.title_calls), 1)
        self.assertTrue(r.get("snapshot"), r)
        self.assertIn(r["snapshot"], r["reason"])

    def test_in_a_batch_no_second_backup(self):
        f = timeline()
        self.use(f)
        r = dispatch.run("batch", {"operations": [{"tool": "titles_to_captions", "args": {"item_ids": ["hello"]}}],
                                   "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(f.calls.count("duplicate_timeline"), 1)
