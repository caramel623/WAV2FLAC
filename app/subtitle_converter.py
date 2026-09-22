from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

# Regex for WebVTT cue timing: 00:01.000 --> 00:04.250
_TIMING_RE = re.compile(
    r"(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>\d{2})[.,](?P<ms>\d{3})"
)
_CUE_LINE_RE = re.compile(
    r"^(?P<start>\S+)\s*-->\s*(?P<end>\S+)"
)
_TAG_RE = re.compile(r"<[^>]+>")
_CUE_NUMBER_RE = re.compile(r"^\s*\d+\s*$")


@dataclass
class VttCue:
    start_ms: int
    end_ms: int
    text: str


def _parse_offset(stem: str, default_h: int = 0) -> int:
    # Support H:MM:SS.mmm or MM:SS.mmm
    parts = [p.replace(",", ".") for p in stem.split(":")]
    try:
        if len(parts) == 1:
            return int(float(parts[0]) * 1000)
        elif len(parts) == 2:
            m, s = parts
            return int(float(m)) * 60000 + int(float(s) * 1000)
        elif len(parts) == 3:
            h, m, s = parts
            return int(float(h)) * 3600000 + int(float(m)) * 60000 + int(float(s) * 1000)
        else:
            return default_h * 3600000
    except (ValueError, AttributeError):
        return 0


def parse_vtt_text(text: str) -> List[VttCue]:
    lines = text.splitlines()
    cues: List[VttCue] = []
    i = 0
    n = len(lines)
    while i < n:
        line_raw = lines[i].rstrip()
        i += 1
        # Skip blank lines, WEBVTT header, NOTE, STYLE regions, cue numbers
        if not line_raw:
            continue
        if line_raw.startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            # skip until blank line for NOTE/STYLE/REGION blocks
            if line_raw.startswith(("NOTE", "STYLE", "REGION")):
                while i < n and lines[i].strip():
                    i += 1
            continue
        if _CUE_NUMBER_RE.match(line_raw):
            # check next line is timing; if so skip this number line
            if i < n and _CUE_LINE_RE.match(lines[i]):
                continue
            else:
                continue
        m = _CUE_LINE_RE.match(line_raw)
        if not m:
            continue
        start_off = _parse_offset(m.group("start"))
        end_off = _parse_offset(m.group("end"))
        # read cue text until blank line
        text_lines: List[str] = []
        while i < n:
            tl = lines[i].rstrip()
            i += 1
            if not tl:
                break
            text_lines.append(tl)
        cue_text = re.sub(r"<[^>]+>", "", "\n".join(text_lines)).strip()
        # join multi-line into a single line separated by newline kept for LRC
        if start_off < end_off:
            cues.append(VttCue(start_ms=start_off, end_ms=end_off, text=cue_text))
    return cues


# Common characters used to score ambiguous CJK decodings (score by hits).
_JA_COMMON = set(
    "のにはをがこれそのためあっていないしからでとも"
    "しいますれるわれるとなりおこないあるくへまで"
    "いれんこうじんひとこえことばたちたなかやう"
    "せなかまたらひふへほへぼまみむめもゆるりるれろわを"
    "うんえりかきくけこしすせそうぞだぢでどばびぶべぼぱぴぷぺ"
)
_ZH_TRAD_COMMON = set(
    "的一是不了人我在有他这为之大来以个中上们到说国和地"
    "也子时道出会三要于自小的学年得就那好她多後間樣說對頭聲來"
    "個麼裡還過沒裡進見請別樣話機聲響見題點讓聽覺問答讀寫"
)
_ZH_SIMP_COMMON = set(
    "的一是不了人我在有他这为之大来以个中上们到说国和地"
    "也子时道出会三要于自小的学年得就那好她多后间样说对头声来"
    "个么里还过没里进见请别样话机声响见题点让听觉问答读写"
)

_ENC_COMMON = {
    "cp932": _JA_COMMON,
    "big5": _ZH_TRAD_COMMON,
    "gb18030": _ZH_SIMP_COMMON,
}


def _score_encoding(data: bytes, enc: str) -> Optional[tuple]:
    try:
        text = data.decode(enc)
    except UnicodeDecodeError:
        return None
    common = _ENC_COMMON[enc]
    score = sum(1 for ch in text if ch in common)
    if score == 0:
        return None
    return score, text


def _cjk_fallback(data: bytes) -> str:
    best = None
    for enc in ("cp932", "big5", "gb18030"):
        r = _score_encoding(data, enc)
        if r and (best is None or r[0] > best[0]):
            best = r
    return best[1] if best else data.decode("utf-8", errors="replace")


def _decode_bytes(data: bytes) -> str:
    data = data.strip(b"\xef\xbb\xbf")  # UTF-8 BOM (utf-8-sig handles rest)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    return _cjk_fallback(data)


def read_vtt(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    return _decode_bytes(data)


def parse_vtt(path: str) -> List[VttCue]:
    return parse_vtt_text(read_vtt(path))


def format_lrc_time(ms: int) -> str:
    # [mm:ss.cc] centiseconds
    total_cs = int(round(ms / 10))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = total_s // 60
    m = m % 60
    return f"[{m:02d}:{s:02d}.{cs:02d}]"


def cues_to_lrc(cues: List[VttCue]) -> str:
    out: List[str] = []
    for cue in cues:
        # Keep multi-line cue text as multiple tagged lines when present
        for line in cue.text.splitlines():
            if not line.strip():
                continue
            out.append(f"{format_lrc_time(cue.start_ms)}{line}")
    if not out and cues:
        out.append(f"{format_lrc_time(cues[0].start_ms)}")
    return "\n".join(out) + ("\n" if out else "")


def cues_to_unsynced(cues: List[VttCue]) -> str:
    lines = [c.text for c in cues if c.text.strip()]
    return "\n".join(lines)
