# WAV2FLAC

Windows GUI batch tool (PySide6) for converting WAV audio to FLAC (lossless)
or M4A/AAC (lossy) and WebVTT subtitles to LRC, with metadata/lyrics
embedding.

## Features

- Batch WAV → FLAC (lossless) or M4A/AAC
- Batch WebVTT → LRC (preserves timestamps)
- Auto-pairing of `.wav` + `.vtt` files by filename stem
- Metadata copy from source (title, artist, album) plus optional LRC lyrics
  embedded into FLAC / M4A
- FFmpeg auto-detection (PATH + common install locations)
- Cancellable batch progress, overwrite / skip / auto-rename policies
- PyInstaller-friendly (no hardcoded paths)

## Requirements

- Python 3.10+
- FFmpeg on PATH or in a common location (ffmpeg.exe + ffprobe.exe)

## Setup

```
pip install -r requirements.txt
```

## Run

```
python main.py
```

## Tests

```
python -m unittest discover -s tests
```
