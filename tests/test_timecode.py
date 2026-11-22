"""Frame rates and timecode."""
import unittest
from fractions import Fraction

from tests import support  # first: gives the tests a temporary bridge folder

from resolve_editor import timecode


class Timecode(unittest.TestCase):
    def test_fps(self):
        self.assertEqual(timecode.parse_fps(30), 30)
        self.assertEqual(timecode.parse_fps("29.97"), Fraction(30000, 1001))
        self.assertEqual(timecode.parse_fps("23.976"), Fraction(24000, 1001))

    def test_round_trip(self):
        for fps, drop in ((30, False), (Fraction(30000, 1001), True), (Fraction(24000, 1001), False), (25, False)):
            for frame in (0, 1, 1799, 1800, 17982, 107892, 108000, 215784):
                self.assertEqual(timecode.tc_to_frame(timecode.frame_to_tc(frame, fps, drop), fps, drop), frame, (fps, drop, frame))

    def test_drop_frame_known_values(self):
        df = Fraction(30000, 1001)
        self.assertEqual(timecode.frame_to_tc(1800, df, True), "00:01:00;02")
        self.assertEqual(timecode.frame_to_tc(17982, df, True), "00:10:00;00")
        self.assertEqual(timecode.frame_to_tc(108000, 30), "01:00:00:00")

    def test_seconds_to_frames_ntsc(self):
        self.assertEqual(timecode.seconds_to_frames(1.001, Fraction(30000, 1001)), 30)
