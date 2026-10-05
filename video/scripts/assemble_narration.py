"""Assemble the narration from the narrator's takes: the main take, the on-camera introduction and pickups.

Each piece is cut at a silence, brought to the main take's loudness, and joined with short fades,
so `timeline.py narration` can align the result like a single take. The on-camera piece keeps its
own audio, so the face and the voice stay in sync; its position in the result is written next to it.

Usage, from the repository root:
    python3 video/scripts/assemble_narration.py
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "video/public/audio/narration-assembled.wav"
FACE = ROOT / "video/public/audio/narration-assembled.json"
RATE = 48_000
TARGET_LUFS = -16.6  # the main take's own loudness
FADE_S = 0.03
# The pieces run about 6 s over the 3-minute limit once the cold open's lead-in and the end card are added.
# Pauses longer than LONG_PAUSE_S are shortened to KEEP_PAUSE_S (the stamps' holds need about 1 s of
# pause, so they stay), then a small tempo change (pitch kept) brings the cut under 3 minutes.
LONG_PAUSE_S = 1.2
KEEP_PAUSE_S = 0.9
TEMPO = 1.03

MAIN = ROOT / "script recording 2.m4a"
PICKUPS = ROOT / "script recording 3.m4a"
PICKUP_REPO = ROOT / "script recording 4.m4a"
CAMERA = ROOT / "IMG_9861.MOV"

# (source, start_s, end_s, gap_after_s, label). Cut points sit in silences found by an energy scan;
# where the main take runs straight on ("agents, and"), a short gap separates the pieces.
PIECES = [
    # The take opens "Hey there, I'm Zeyu." (1.6 to 2.8 s); the on-camera "Hi, I'm Zeyu" follows the
    # hook a few seconds later, so the take starts at the hook itself.
    (MAIN, 3.3, 10.0, 0.0, "main: This is a coding agent ... Well, it didn't."),
    (CAMERA, 1.9, 6.15, 0.25, "camera: Hi, I'm Zeyu. I build evaluations for AI agents."),
    # "agents," in the main take ends at 14.0 s (its final "s" is the loud sibilant at 13.84 to 13.98 s);
    # whisper's word times put it 0.6 s early. The cut sits in the silence before "and" (14.28 s).
    (MAIN, 14.15, 76.50, 0.4, "main: And I have heard done a lot ... runs the tests itself. Rejected."),
    # The take says "Rejected. Oh, the spec still fails."; "Oh," (76.64 to 76.92 s) is cut.
    (MAIN, 77.06, 153.2, 0.0, "main: The spec still fails. ... about forty cents of Nemotron tokens each."),
    (PICKUPS, 6.35, 15.7, 0.5, "pickup: It all ran on Nebius Token Factory ... nearly five hundred sandboxes."),
    (MAIN, 161.5, 168.6, 0.0, "main: That's what I want ... a receipt I can re-run."),
    (PICKUP_REPO, 0.85, 5.35, 0.6, "pickup: Here it is on another repo: one command and a failing test."),
    (MAIN, 172.45, 177.9, 0.0, "main: Agents can write the code. Receipts make them show their work."),
]


def _loudness(path: Path) -> float:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    blob = out[out.rindex("{"): out.rindex("}") + 1]
    return float(json.loads(blob)["input_i"])


def _shorten_pauses(source: Path, target: Path) -> tuple[Path, float]:
    """Shorten every pause longer than LONG_PAUSE_S to KEEP_PAUSE_S, cutting from its middle."""

    import numpy as np

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-f", "f32le", "-ac", "1", "-ar", str(RATE), "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    hop = RATE // 100  # 10 ms
    frames = len(audio) // hop
    level = 20 * np.log10(np.sqrt((audio[:frames * hop].reshape(frames, hop) ** 2).mean(1)) + 1e-9)
    quiet = level < np.percentile(level, 95) - 38
    keep = np.ones(len(audio), dtype=bool)
    removed = 0.0
    start = None
    for index in range(frames + 1):
        silent = index < frames and quiet[index]
        if silent and start is None:
            start = index
        elif not silent and start is not None:
            length = (index - start) / 100
            if length > LONG_PAUSE_S:
                cut = length - KEEP_PAUSE_S
                middle = start * hop + int((length / 2) * RATE)
                half = int(cut / 2 * RATE)
                keep[middle - half: middle + half] = False
                removed += cut
            start = None
    audio = audio[keep]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ac", "1", "-ar", str(RATE), "-i", "-", str(target)],
                   input=audio.tobytes(), check=True)
    return target, removed


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        parts: list[Path] = []
        clock = 0.0
        face = None
        for index, (source, start, end, gap, label) in enumerate(PIECES):
            raw = tmpdir / f"{index:02d}-raw.wav"
            denoise = ",afftdn=nf=-30" if source == CAMERA else ""
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-to", str(end), "-i", str(source), "-vn",
                 "-ac", "1", "-ar", str(RATE), "-af", f"highpass=f=80{denoise}", str(raw)],
                check=True,
            )
            gain = TARGET_LUFS - _loudness(raw)
            length = end - start
            piece = tmpdir / f"{index:02d}.wav"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af",
                 f"volume={gain:.2f}dB,afade=t=in:d={FADE_S},afade=t=out:st={length - FADE_S:.3f}:d={FADE_S}"
                 + (f",apad=pad_dur={gap}" if gap else ""),
                 "-ar", str(RATE), str(piece)],
                check=True,
            )
            if source == CAMERA:
                face = {"start_s": round(clock, 3), "end_s": round(clock + length, 3),
                        "source_start_s": start, "source": CAMERA.name}
            print(f"{clock:7.2f}s  {length:6.2f}s  gain {gain:+5.1f} dB  {label}")
            clock += length + gap
            parts.append(piece)
        listing = tmpdir / "parts.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        joined = tmpdir / "joined.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", str(joined)], check=True)
        tightened, removed = _shorten_pauses(joined, tmpdir / "tightened.wav")
        print(f"pauses: {removed:.1f}s removed from pauses longer than {LONG_PAUSE_S}s")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(tightened), "-af",
             f"atempo={TEMPO}",
             "-ar", str(RATE), str(OUT)],
            check=True,
        )
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                  str(OUT)], capture_output=True, text=True, check=True).stdout)
    # The face's place in the final timeline comes from the aligned words of its sentence; these
    # pre-tempo times are kept only as a record of the cut.
    FACE.write_text(json.dumps({"joined_s": round(clock, 3), "total_s": round(total, 3), "tempo": TEMPO,
                                "face_before_tempo": face}, indent=2) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {clock:.1f}s joined, {total:.1f}s at tempo {TEMPO}")


if __name__ == "__main__":
    main()
