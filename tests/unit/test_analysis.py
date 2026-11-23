"""Onset detection and QC parsing."""
from tests.support import Base

from resolve_editor.tools import delivery, markers


class Analysis(Base):
    def test_onsets(self):
        rate, s = 11025, []
        for _ in range(4):
            s += [0.8] * 1000 + [0.0] * (rate // 2 - 1000)
        self.assertGreaterEqual(len(markers.onsets(s, rate)), 3)

    def test_qc_parse(self):
        log = ("[blackdetect] black_start:0 black_end:0.8\n[freezedetect] freeze_start: 3.2\n"
               "  Integrated loudness:\n    I:         -14.2 LUFS\n  Loudness range:\n    LRA:         5.1 LU\n"
               "  True peak:\n    Peak:       -0.5 dBFS\n")
        r = delivery.parse_qc(log)
        self.assertEqual((r["integrated_lufs"], r["true_peak_dbfs"], r["black_segments"]), (-14.2, -0.5, [[0.0, 0.8]]))
