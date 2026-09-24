import os
import tempfile
import shutil
import unittest
import zipfile

from app import updater
from app.updater import compare_versions, _parse_version, _extract_zip, _find_new_dir, UpdateWorker


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


class TestDownload(unittest.TestCase):
    def test_download_reports_3arg_progress(self):
        import http.server, socketserver, threading

        root = tempfile.mkdtemp()
        served = os.path.join(root, "data.bin")
        with open(served, "wb") as f:
            f.write(os.urandom(300 * 1024))
        payload = open(served, "rb").read()

        class H(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=root, **kw)

            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        with socketserver.TCPServer(("127.0.0.1", 0), H) as httpd:
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()

            dest = os.path.join(root, "out.zip")
            got: List = []
            w = UpdateWorker("0.0.1")
            w.progress.connect(lambda p, d, s: got.append((p, d, s)))
            w._download(f"http://127.0.0.1:{port}/data.bin", dest)
            httpd.shutdown()

            self.assertTrue(os.path.isfile(dest))
            self.assertEqual(os.path.getsize(dest), len(payload))
            self.assertTrue(got, "no progress emitted")
            p, d, s = got[-1]
            self.assertEqual(p, 100)
            self.assertGreater(s, 0)
        shutil.rmtree(root)

    def test_download_cancel(self):
        dest = os.path.join(tempfile.mkdtemp(), "out.zip")
        w = UpdateWorker("0.0.1")
        w.request_cancel()  # 取消旗標已啟動
        with self.assertRaises(InterruptedError):
            w._download("http://127.0.0.1:1/never", dest)

    def test_progress_format(self):
        from app.main_window import MainWindow
        f = MainWindow._fmt_progress
        self.assertIn("連線中", f(0, 0, 0.0))
        self.assertIn("速度很慢", f(10, 1_000_000, 20_000.0))
        self.assertIn("MB/s", f(50, 20_000_000, 3_000_000.0))
        self.assertNotIn("約剩", f(100, 40_000_000, 1_000_000.0))


if __name__ == "__main__":
    unittest.main()
