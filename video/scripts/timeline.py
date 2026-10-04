"""Build the video's timeline (one beat per narration paragraph) and its voice track.

Two sources, one output format (`video/src/content/timeline.json` plus a WAV in `video/public/audio/`):

- `scratch`: synthesizes each paragraph of the narration with the macOS `say` voice, only to time
  the cut before the narrator records. It is a placeholder and is labelled as one.
- `narration`: takes the narrator's own recording, transcribes it with whisper.cpp for word
  timings, and finds where each paragraph starts and ends. (Implemented when the recording arrives.)

The narration text is read from `docs/submission/video-script.md`, section "The narration to record
(revision 5)": paragraphs are blocks of `>` lines separated by an empty `>` line, and `/` marks a pause.

Usage, from the repository root:
    python3 video/scripts/timeline.py scratch
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docs/submission/video-script.md"
DATA = ROOT / "video/src/content/timeline.json"
AUDIO_DIR = ROOT / "video/public/audio"
BEATS = [
    "cold_open", "who_and_numbers", "receipts", "featured_setup", "agent_works", "rejected",
    "appeal_passes", "checks_and_official", "reverify", "pilot_story", "results", "close",
]
LEAD_IN_S = 2.0  # the cold open types the agent's message before the first word
GAP_S = 0.5
END_HOLD_S = 4.0
PAUSE_MS = 700
SAMPLE_RATE = 48_000


def paragraphs() -> list[str]:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("## The narration to record (revision 5)")
    end = text.index("### How to say it", start)
    blocks: list[list[str]] = [[]]
    for line in text[start:end].splitlines():
        if not line.startswith(">"):
            continue
        body = line[1:].strip()
        if body:
            blocks[-1].append(body)
        elif blocks[-1]:
            blocks.append([])
    found = [" ".join(block) for block in blocks if block]
    if len(found) != len(BEATS):
        raise SystemExit(f"expected {len(BEATS)} narration paragraphs, found {len(found)}")
    return found


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(out.strip())


def scratch(rate_wpm: int = 125) -> None:
    texts = paragraphs()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    beats = []
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        parts: list[Path] = []
        silence = tmpdir / "gap.wav"
        lead = tmpdir / "lead.wav"
        tail = tmpdir / "tail.wav"
        for name, seconds in ((silence, GAP_S), (lead, LEAD_IN_S), (tail, END_HOLD_S)):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"anullsrc=r={SAMPLE_RATE}:cl=mono", "-t", str(seconds), str(name)], check=True)
        parts.append(lead)
        clock = LEAD_IN_S
        for index, (beat, text) in enumerate(zip(BEATS, texts)):
            spoken = text.replace("/", f"[[slnc {PAUSE_MS}]]")
            aiff = tmpdir / f"{index:02d}.aiff"
            wav = tmpdir / f"{index:02d}.wav"
            subprocess.run(["say", "-v", "Samantha", "-r", str(rate_wpm), "-o", str(aiff), spoken], check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ar", str(SAMPLE_RATE), "-ac", "1", str(wav)], check=True)
            length = _duration(wav)
            beats.append({"id": beat, "text": text.replace(" /", "").replace("/", ""), "start_s": round(clock, 3), "end_s": round(clock + length, 3)})
            clock += length
            parts.append(wav)
            if index < len(texts) - 1:
                parts.append(silence)
                clock += GAP_S
        parts.append(tail)
        clock += END_HOLD_S
        listing = tmpdir / "parts.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        out = AUDIO_DIR / "scratch-voice.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)], check=True)
    timeline = {
        "source": "scratch: macOS Samantha voice, a placeholder to time the cut; the final video uses the narrator's recording",
        "voice": "audio/scratch-voice.wav",
        "fps": 30,
        "lead_in_s": LEAD_IN_S,
        "end_hold_s": END_HOLD_S,
        "total_s": round(clock, 3),
        "beats": beats,
    }
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(timeline, indent=2) + "\n", encoding="utf-8")
    print(f"scratch voice {clock:.1f}s over {len(beats)} beats -> {DATA.relative_to(ROOT)}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "scratch":
        rate = int(sys.argv[2]) if len(sys.argv) > 2 else 125
        scratch(rate)
    else:
        raise SystemExit("usage: timeline.py scratch [WPM]")
