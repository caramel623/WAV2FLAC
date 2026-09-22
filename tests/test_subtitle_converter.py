import unittest

from app.subtitle_converter import (
    _decode_bytes,
    cues_to_lrc,
    cues_to_unsynced,
    format_lrc_time,
    parse_vtt_text,
)


class TestDecodeBytes(unittest.TestCase):
    def test_japanese_shift_jis(self):
        text = "これは日本語の歌詞"
        self.assertEqual(_decode_bytes(text.encode("cp932")), text)

    def test_traditional_chinese_big5(self):
        text = "這是繁體中文"
        self.assertEqual(_decode_bytes(text.encode("big5")), text)

    def test_simplified_gb18030(self):
        text = "这是简体中文"
        self.assertEqual(_decode_bytes(text.encode("gb18030")), text)

    def test_english_digits_symbols(self):
        text = "Hello 2024 Rock & Roll @#%!"
        self.assertEqual(_decode_bytes(text.encode("utf-8")), text)

    def test_utf8_bom(self):
        text = "Hello"
        self.assertEqual(_decode_bytes(b"\xef\xbb\xbf" + text.encode("utf-8")), text)


class TestFormatLrcTime(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(format_lrc_time(0), "[00:00.00]")

    def test_seconds_centis(self):
        self.assertEqual(format_lrc_time(1000), "[00:01.00]")
        self.assertEqual(format_lrc_time(4250), "[00:04.25]")
        self.assertEqual(format_lrc_time(61_350), "[01:01.35]")


class TestParseVttText(unittest.TestCase):
    def test_timestamps_and_tags(self):
        vtt = (
            "WEBVTT\n"
            "\n"
            "00:01.000 --> 00:04.250\n"
            "第一句\n"
            "\n"
            "00:05.000 --> 00:08.000\n"
            "<i>第二句</i>\n"
        )
        cues = parse_vtt_text(vtt)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start_ms, 1000)
        self.assertEqual(cues[0].end_ms, 4250)
        self.assertEqual(cues[0].text, "第一句")
        self.assertEqual(cues[1].text, "第二句")

    def test_multiline_cue_joined(self):
        vtt = (
            "WEBVTT\n"
            "\n"
            "00:00.000 --> 00:03.000\n"
            "第一句\n"
            "第二句 第二行\n"
            "\n"
        )
        cues = parse_vtt_text(vtt)
        self.assertEqual(len(cues), 1)
        self.assertIn("第一句", cues[0].text)
        self.assertIn("第二行", cues[0].text)

    def test_comma_decimal(self):
        vtt = "00:01,000 --> 00:04,250\nline\n"
        cues = parse_vtt_text(vtt)
        self.assertEqual(cues[0].start_ms, 1000)
        self.assertEqual(cues[0].end_ms, 4250)

    def test_cue_number(self):
        vtt = "WEBVTT\n\n1\n00:01.000 --> 00:02.000\ntext\n"
        cues = parse_vtt_text(vtt)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].start_ms, 1000)


class TestLrcOutput(unittest.TestCase):
    def test_lrc_format(self):
        vtt = (
            "WEBVTT\n"
            "\n"
            "00:01.000 --> 00:04.250\n"
            "第一句\n"
            "\n"
            "00:04.250 --> 00:08.000\n"
            "第二句 第二行\n"
        )
        cues = parse_vtt_text(vtt)
        lrc = cues_to_lrc(cues)
        self.assertIn("[00:01.00]", lrc)
        self.assertIn("[00:04.25]", lrc)
        self.assertIn("第一句", lrc)
        self.assertIn("第二行", lrc)

    def test_unsynced(self):
        vtt = "WEBVTT\n\n00:01.000 --> 00:02.000\nA\n\n00:02.000 --> 00:03.000\nB\n"
        cues = parse_vtt_text(vtt)
        unsynced = cues_to_unsynced(cues)
        self.assertEqual(unsynced, "A\nB")


if __name__ == "__main__":
    unittest.main()
