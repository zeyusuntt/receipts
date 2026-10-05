"""Build the video's timeline (one beat per narration paragraph) and its voice track.

Two sources, one output format (`video/src/content/timeline.json` plus a WAV in `video/public/audio/`):

- `scratch`: synthesizes each paragraph of the narration with the macOS `say` voice, only to time
  the cut before the narrator records. It is a placeholder and is labelled as one.
- `narration`: takes the narrator's own recording, transcribes it with whisper.cpp for word
  timings, and finds where each paragraph starts and ends. (Implemented when the recording arrives.)

The narration text is read from `docs/submission/video-script.md`, section "The narration to record
(revision 6)": paragraphs are blocks of `>` lines separated by an empty `>` line, and `/` marks a pause.

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
END_HOLD_S = 3.0  # the close card stays up for its own sentence plus this hold
PAUSE_MS = 700
SAMPLE_RATE = 48_000


def paragraphs() -> list[str]:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("## The narration to record (revision 6)")
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


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
# The larger model hears an accented narrator far better (88% to over 95% of words matched); the small
# one is the fallback when the large file has not been downloaded.
_LARGE = ROOT / "video/.models/ggml-large-v3-turbo-q5_0.bin"
MODEL = _LARGE if _LARGE.exists() else ROOT / "video/.models/ggml-small.en.bin"
# Proper nouns whisper would otherwise mishear.
VOCABULARY = ("I'm Zeyu. NVIDIA Nemotron 3 Super, SWE-rebench, Nebius Token Factory, "
              "Token Factory Sandbox, PyFilesystem2, Receipts, Docker.")


def _number_words(n: int) -> list[str]:
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_ONES[n % 10]] if n % 10 else [])
    if n == 100:
        return ["hundred"]
    return [str(n)]


def _tokens(text: str) -> list[str]:
    """Lower-case words for alignment: punctuation dropped, hyphens split, digits spelled out."""
    out: list[str] = []
    for raw in re.split(r"[\s/\-]+", text.lower()):
        word = re.sub(r"[^a-z0-9']", "", raw).strip("'")
        if not word:
            continue
        if word.isdigit():
            out.extend(_number_words(int(word)))
        else:
            out.append(word)
    return out


def _transcribe(wav16k: Path, workdir: Path) -> list[tuple[str, float, float]]:
    subprocess.run(["whisper-cli", "-m", str(MODEL), "-f", str(wav16k), "-ml", "1", "-sow",
                    "--prompt", VOCABULARY, "-ojf", "-of", str(workdir / "words"), "-np"],
                   check=True, capture_output=True)
    data = json.loads((workdir / "words.json").read_text())
    words = []
    for segment in data["transcription"]:
        text = segment["text"].strip()
        if not text:
            continue
        words.append((text, segment["offsets"]["from"] / 1000, segment["offsets"]["to"] / 1000))
    return words


def _display_words(text: str, beat_index: int, script_tokens: list[tuple[int, str]], mapped: dict[int, int],
                   heard: list[tuple[str, float, float]], shift: float, start: float, end: float) -> list[dict]:
    """Every word of the script as written (case, punctuation, digits kept, for the captions), timed.

    A word takes the span of its heard tokens; a word the transcription missed (an accent, a name)
    is placed evenly in the gap between its timed neighbours, so captions and cues never drop it."""

    first = next(i for i, (p, _) in enumerate(script_tokens) if p == beat_index)
    cursor = first
    words: list[dict] = []
    for display in text.split():
        count = len(_tokens(display))
        hits = [mapped[i] for i in range(cursor, cursor + count) if i in mapped]
        cursor += count
        if hits:
            words.append({"w": display, "start_s": heard[min(hits)][1] + shift, "end_s": heard[max(hits)][2] + shift})
        else:
            words.append({"w": display, "start_s": None, "end_s": None})
    i = 0
    while i < len(words):
        if words[i]["start_s"] is not None:
            i += 1
            continue
        j = i
        while j < len(words) and words[j]["start_s"] is None:
            j += 1
        left = words[i - 1]["end_s"] if i > 0 else start
        right = words[j]["start_s"] if j < len(words) else end
        step = max(right - left, 0.0) / (j - i)
        for k in range(i, j):
            words[k]["start_s"] = left + step * (k - i)
            words[k]["end_s"] = left + step * (k - i + 1)
        i = j
    return [{"w": w["w"], "start_s": round(w["start_s"], 3), "end_s": round(w["end_s"], 3)} for w in words]


def narration(recording: Path) -> None:
    """Time the beats to the narrator's own recording, cleaned and loudness-normalised."""
    import difflib

    texts = paragraphs()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        cleaned = tmpdir / "cleaned.wav"
        # High-pass rumble, light FFT denoise, then broadcast loudness (-16 LUFS, -1.5 dBTP).
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(recording), "-ac", "1", "-ar", str(SAMPLE_RATE),
                        "-af", "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,"
                        "highpass=f=80,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11", str(cleaned)], check=True)
        wav16k = tmpdir / "16k.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(cleaned), "-ac", "1", "-ar", "16000", str(wav16k)], check=True)
        words = _transcribe(wav16k, tmpdir)
        heard: list[tuple[str, float, float]] = []
        for text, start, end in words:
            for token in _tokens(text):
                heard.append((token, start, end))
        script_tokens: list[tuple[int, str]] = []
        for index, text in enumerate(texts):
            script_tokens.extend((index, token) for token in _tokens(text))
        matcher = difflib.SequenceMatcher(a=[t for _, t in script_tokens], b=[t for t, _, _ in heard], autojunk=False)
        mapped: dict[int, int] = {}
        for block in matcher.get_matching_blocks():
            for k in range(block.size):
                mapped[block.a + k] = block.b + k
        matched_heard = set(mapped.values())
        # Lead-in: the cold open needs LEAD_IN_S before the first word.
        first_word = heard[min(mapped.values())][1] if mapped else 0.0
        shift = max(0.0, LEAD_IN_S - first_word)
        beats = []
        for index, beat in enumerate(BEATS):
            positions = [i for i, (p, _) in enumerate(script_tokens) if p == index and i in mapped]
            if not positions:
                raise SystemExit(f"could not find beat {beat} in the recording; check the take")
            start = heard[mapped[positions[0]]][1] + shift
            end = heard[mapped[positions[-1]]][2] + shift
            text = texts[index].replace(" /", "").replace("/", "")
            beats.append({"id": beat, "text": text, "start_s": round(start, 3), "end_s": round(end, 3),
                          "words": _display_words(text, index, script_tokens, mapped, heard, shift, start, end)})
        extra = [(t, round(s + shift, 2), round(e + shift, 2)) for i, (t, s, e) in enumerate(heard) if i not in matched_heard]
        voice_end = _duration(cleaned) + shift
        total = max(voice_end, beats[-1]["end_s"]) + END_HOLD_S
        out = AUDIO_DIR / "narration.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(cleaned), "-af", f"adelay={int(shift * 1000)}",
                        "-ar", str(SAMPLE_RATE), "-ac", "1", str(out)], check=True)
    coverage = len(mapped) / max(1, len(script_tokens))
    timeline = {
        "source": f"narration: the narrator's recording {recording.name}, cleaned and aligned with whisper.cpp",
        "voice": "audio/narration.wav",
        "fps": 30,
        "lead_in_s": round(beats[0]["start_s"], 3),
        "end_hold_s": END_HOLD_S,
        "total_s": round(total, 3),
        "alignment": {"script_words_matched": round(coverage, 3), "unmatched_heard_words": extra},
        "beats": beats,
    }
    DATA.write_text(json.dumps(timeline, indent=2) + "\n", encoding="utf-8")
    print(f"narration {total:.1f}s, {coverage:.0%} of script words matched, {len(extra)} extra words heard -> {DATA.relative_to(ROOT)}")
    if total > 179:
        print("WARNING: longer than 2:59; trim a sentence before rendering")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "scratch":
        rate = int(sys.argv[2]) if len(sys.argv) > 2 else 125
        scratch(rate)
    elif mode == "narration" and len(sys.argv) > 2:
        narration(Path(sys.argv[2]))
    else:
        raise SystemExit("usage: timeline.py scratch [WPM] | timeline.py narration RECORDING")
