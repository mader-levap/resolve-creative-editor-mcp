"""Clip volume, pan and normalization."""
from tests.support import Base, FakeResolve, item

from resolve_editor import dispatch


class Props(FakeResolve):
    """Keeps what set_item_properties sets, so read-back sees it; refuse: properties Resolve ignores."""

    refuse: set[str] = set()

    def __call__(self, op, args, **kw):
        if op == "set_item_properties":
            props = self.settings[args["item_id"]]["properties"]
            props.update({k: v for k, v in args["properties"].items() if k not in self.refuse})
        if op == "normalize_audio":
            self.normalized = dict(args)
        return super().__call__(op, args, **kw)


def audio(id="a"):
    return item(id, 1000, 10, kind="audio")


class SetAudio(Base):
    def test_volume_and_pan_are_set_and_read_back(self):
        f = self.use(Props([audio()]))
        r = dispatch.run("set_audio", {"item_ids": ["a"], "volume_db": -6, "pan": 0.5})
        self.assertEqual((r["_operation"]["status"], r["_operation"]["changes"]["items_changed"]), ("success", 1), r)
        self.assertEqual({k: f.settings["a"]["properties"][k] for k in ("AudioVolume", "AudioPan")},
                         {"AudioVolume": -6.0, "AudioPan": 0.5})

    def test_a_value_resolve_ignores_is_partial(self):
        f = self.use(Props([audio(), audio("b")]))
        f.refuse = {"AudioPan"}
        r = dispatch.run("set_audio", {"item_ids": ["a", "b"], "pan": -1})
        self.assertEqual((r["_operation"]["status"], r["_operation"]["changes"]["items_changed"]), ("partial", 0), r)
        self.assertIn("clamped", " ".join(r["_operation"]["warnings"]))

    def test_nothing_to_set_is_refused_before_writing(self):
        f = self.use(Props([audio()]))
        r = dispatch.run("set_audio", {"item_ids": ["a"]})
        self.assertEqual(r["_operation"]["status"], "blocked")
        self.assertNotIn("set_item_properties", f.calls)


class Normalize(Base):
    def test_unknown_mode_is_refused_naming_the_modes(self):
        f = self.use(Props([audio()]))
        r = dispatch.run("normalize_audio", {"item_ids": ["a"], "mode": "LOUD", "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "blocked")
        self.assertIn("EBU R128", r["reason"])
        self.assertNotIn("normalize_audio", f.calls)

    def test_preview_shows_the_options_and_changes_nothing(self):
        f = self.use(Props([audio()]))
        r = dispatch.run("normalize_audio", {"item_ids": ["a"], "target_level": -1, "target_loudness": -14})
        self.assertEqual(r["_operation"]["status"], "preview")
        self.assertEqual(r["plan"]["options"], {"normalizationMode": "EBU R128", "targetLevel": -1,
                                                "targetLoudness": -14,
                                                "setLevelMode": "NORMALIZE_AUDIO_SET_LEVEL_RELATIVE"})
        self.assertNotIn("normalize_audio", f.calls)

    def test_confirm_sends_the_options_and_says_it_cant_be_verified(self):
        f = self.use(Props([audio(), audio("b")]))
        r = dispatch.run("normalize_audio", {"item_ids": ["a", "b"], "independent": True, "confirm": True,
                                             "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(r["_operation"]["verification"], "unverified", "normalization gain can't be read back")
        self.assertEqual(f.normalized["item_ids"], ["a", "b"])
        self.assertEqual(f.normalized["options"]["setLevelMode"], "NORMALIZE_AUDIO_SET_LEVEL_INDEPENDENT")
        self.assertIn("listen", " ".join(r["_operation"]["warnings"]))
