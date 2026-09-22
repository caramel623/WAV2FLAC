import os
import tempfile
import shutil
import unittest
import zipfile

from app import updater
from app.updater import compare_versions, _parse_version, _extract_zip, _find_new_dir


class TestVersions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(_parse_version("v0.10.1"), (0, 10, 1))
        self.assertEqual(_parse_version("1.2"), (1, 2, 0))
        self.assertEqual(_parse_version("v1.0-alpha"), (1, 0, 0))

    def test_compare(self):
        self.assertLess(compare_versions("0.0.2", "0.0.3"), 0)
        self.assertLess(compare_versions("0.1.0", "1.0.0"), 0)
        self.assertEqual(compare_versions("1.0.0", "1.0.0"), 0)
        self.assertGreater(compare_versions("2.0", "1.9.9"), 0)


class TestExtract(unittest.TestCase):
    def test_extract_cjk_find_exe(self):
        root = tempfile.mkdtemp()
        src = os.path.join(root, "WAV2FLAC-v0.0.3")
        os.makedirs(os.path.join(src, "LRC/繁體"), exist_ok=True)
        with open(os.path.join(src, "WAV2FLAC.exe"), "wb") as f:
            f.write(b"x")
        with open(os.path.join(src, "LRC/繁體/a.txt"), "w", encoding="utf-8") as f:
            f.write("一")
        z = os.path.join(root, "pkg.zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(os.path.join(src, "WAV2FLAC.exe"), "WAV2FLAC/WAV2FLAC.exe")
            zf.write(os.path.join(src, "LRC/繁體/a.txt"), "WAV2FLAC/LRC/繁體/a.txt")
        dest = os.path.join(root, "out")
        os.makedirs(dest)
        updater._extract_zip(z, dest)
        nd = _find_new_dir(dest)
        self.assertTrue(os.path.isfile(os.path.join(nd, "WAV2FLAC.exe")))
        self.assertTrue(os.path.isfile(os.path.join(nd, "LRC", "繁體", "a.txt")))
        shutil.rmtree(root)

    def test_install_dir(self):
        self.assertTrue(os.path.isdir(updater.install_dir()))


if __name__ == "__main__":
    unittest.main()
