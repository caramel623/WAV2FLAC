import os
import tempfile
import shutil
import unittest
import zipfile

from app import archive


class TestArchive(unittest.TestCase):
    def test_is_archive(self):
        self.assertTrue(archive.is_archive("a.zip"))
        self.assertTrue(archive.is_archive("a.7z"))
        self.assertTrue(archive.is_archive("a.rar"))
        self.assertFalse(archive.is_archive("a.wav"))
        self.assertFalse(archive.is_archive("a.vtt"))

    def test_find_7z(self):
        # 可能已安裝也可能未安裝;兩種都合法
        found = archive.find_7z()
        self.assertTrue(found is None or os.path.isfile(found))

    def test_zip_extract_cjk_names(self):
        root = tempfile.mkdtemp()
        src = os.path.join(root, "src")
        os.makedirs(os.path.join(src, "LRC/繁體"), exist_ok=True)
        with open(os.path.join(src, "LRC/繁體/01.lrc"), "w", encoding="utf-8") as f:
            f.write("[00:00.00]一\n")
        zip_path = os.path.join(root, "t.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(os.path.join(src, "LRC/繁體/01.lrc"), "LRC/繁體/01.lrc")
        out = os.path.join(root, "out")
        archive.extract_archive(zip_path, out)
        target = os.path.join(out, "LRC", "繁體", "01.lrc")
        self.assertTrue(os.path.isfile(target), "CJK path missing")
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "[00:00.00]一\n")
        shutil.rmtree(root)

    def test_decode_name_no_flag_encodings(self):
        # 模擬 Python 以 cp437 誤解的「未設 UTF-8 flag」情況, 驗證各 CJK 編碼還原
        for real in ("LRC/繁體/01.lrc",   # Big5 來源
                     "音源/曲名.wav",       # cp932(日/中)
                     "歌01.wav"):           # 一般
            raw = real.encode("big5") if "繁" in real else real.encode("cp932")
            mangled = raw.decode("cp437")   # zipfile 未 flag 時得到的字串
            got = archive._decode_name(mangled, False)
            self.assertEqual(got, real, f"failed for {real!r}")
        # UTF-8 來源的 no-flag 還原
        raw = "甲/乙.wav".encode("utf-8")
        got = archive._decode_name(raw.decode("cp437"), False)
        self.assertEqual(got, "甲/乙.wav")
        # 純 ASCII 不受影響
        self.assertEqual(archive._decode_name("abc.wav", False), "abc.wav")
        # is_utf8=True 原樣回傳
        self.assertEqual(archive._decode_name("繁體/乙.wav", True), "繁體/乙.wav")

    @unittest.skipUnless(archive.find_7z(), "7-Zip not installed")
    def test_7z_extract(self):
        seven = archive.find_7z()
        root = tempfile.mkdtemp()
        src = os.path.join(root, "src")
        os.makedirs(os.path.join(src, "WAV"))
        with open(os.path.join(src, "WAV/01.wav"), "w", encoding="utf-8") as f:
            f.write("x")
        arc = os.path.join(root, "t.7z")
        import subprocess
        subprocess.run([seven, "a", "-y", arc, src],
                       capture_output=True, encoding="utf-8", errors="replace")
        out = os.path.join(root, "out")
        archive.extract_archive(arc, out)
        self.assertTrue(os.path.isfile(os.path.join(out, "src", "WAV", "01.wav")))
        shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
