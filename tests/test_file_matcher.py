import os
import tempfile
import unittest

from app.file_matcher import PairStatus, scan_paths


def _mk(root, name, content="") -> str:
    os.makedirs(root, exist_ok=True)
    p = os.path.join(root, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


class TestScanPaths(unittest.TestCase):
    def _setup(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.audio = os.path.join(self.tmp.name, "audio")
        self.subs = os.path.join(self.tmp.name, "subs")
        return self.audio, self.subs

    def test_matched_pair(self):
        a, s = self._setup()
        _mk(a, "song.wav")
        _mk(s, "song.vtt")
        pairs = scan_paths([a], [s], "out")
        matched = [p for p in pairs if p.status == PairStatus.MATCHED]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].stem, "song")
        self.assertTrue(matched[0].ready)
        self.tmp.cleanup()

    def test_missing_subtitle(self):
        a, s = self._setup()
        _mk(a, "solo.wav")
        pairs = scan_paths([a], [s], "out")
        states = {p.stem: p.status for p in pairs}
        self.assertEqual(states["solo"], PairStatus.MISSING_SUBTITLE)
        self.tmp.cleanup()

    def test_missing_audio(self):
        a, s = self._setup()
        _mk(s, "orphan.vtt")
        pairs = scan_paths([a], [s], "out")
        states = {p.stem: p.status for p in pairs}
        self.assertEqual(states["orphan"], PairStatus.MISSING_AUDIO)
        self.tmp.cleanup()

    def test_unicode_stem(self):
        a, s = self._setup()
        name = "歌 2024"
        _mk(a, name + ".wav")
        _mk(s, name + ".vtt")
        pairs = scan_paths([a], [s], "out")
        matched = [p for p in pairs if p.status == PairStatus.MATCHED]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].stem, name)
        self.tmp.cleanup()

    def test_single_files(self):
        tmp = tempfile.TemporaryDirectory()
        a = _mk(tmp.name, "x.wav")
        s = _mk(tmp.name, "x.vtt")
        pairs = scan_paths([a], [s], "out")
        matched = [p for p in pairs if p.status == PairStatus.MATCHED]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].stem, "x")
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
