"""Measurable signals from a video: sentences, hook frames, cuts, audio spikes.

The parsing/maths functions are pure so they can be tested without media.
"""
from __future__ import annotations

import math
import re
import statistics
import subprocess
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path

from bada.youtube.media import MediaError

FRAME_STEP = 0.125  # seconds between hook frames
HOOK_SECONDS = 3.0


# ---------- sentences ----------

_SENTENCE_END = re.compile(r"[.!?。！？…]$")


@dataclass
class Sentence:
    start: float
    end: float
    text: str


def group_sentences(words: list[tuple[float, float, str]], max_pause: float = 0.6, max_len: float = 8.0) -> list[Sentence]:
    """Join whisper words into sentences: break on end punctuation, a pause longer
    than `max_pause`, or a run longer than `max_len` seconds."""
    sentences: list[Sentence] = []
    cur: list[tuple[float, float, str]] = []

    def flush():
        if cur:
            text = "".join(w[2] for w in cur).strip()
            if text:
                sentences.append(Sentence(round(cur[0][0], 2), round(cur[-1][1], 2), text))
            cur.clear()

    for word in words:
        if cur and (word[0] - cur[-1][1] > max_pause or word[1] - cur[0][0] > max_len):
            flush()
        cur.append(word)
        if _SENTENCE_END.search(word[2].strip()):
            flush()
    flush()
    return sentences


# ---------- hook frames ----------

def extract_hook_frames(video: Path, out_dir: Path, seconds: float = HOOK_SECONDS, step: float = FRAME_STEP) -> list[Path]:
    """Full-resolution PNG every `step` seconds for the first `seconds`, plus a contact sheet."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = round(1 / step)
    pattern = out_dir / "f_%03d.png"
    _ffmpeg(["-i", str(video), "-t", f"{seconds}", "-vf", f"fps={fps}", "-start_number", "0", str(pattern)])
    frames = []
    for i, f in enumerate(sorted(out_dir.glob("f_*.png"))):
        named = out_dir / f"{i * step:06.3f}s.png"
        f.rename(named)
        frames.append(named)
    cols = 6
    rows = max(1, math.ceil(len(frames) / cols))
    _ffmpeg(["-i", str(video), "-t", f"{seconds}", "-vf", f"fps={fps},scale=240:-2,tile={cols}x{rows}",
             "-frames:v", "1", "-q:v", "3", str(out_dir / "sheet.jpg")])
    return frames


# ---------- cuts ----------

_PTS = re.compile(r"pts_time:([\d.]+)")


def parse_scene_times(stderr: str) -> list[float]:
    return [round(float(m.group(1)), 3) for m in _PTS.finditer(stderr)]


def detect_cuts(video: Path, threshold: float = 0.3) -> list[float]:
    err = _ffmpeg(["-i", str(video), "-an", "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"])
    return parse_scene_times(err)


# ---------- audio ----------

@dataclass
class AudioSpike:
    time: float
    db: float
    jump_db: float
    kind: str  # "jump" (sudden loudness) or "clip" (digital clipping)


def read_pcm(video: Path, rate: int = 8000) -> array:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(rate),
                          "-f", "s16le", "-"], capture_output=True)
    if out.returncode != 0:
        return array("h")  # no audio stream
    pcm = array("h")
    pcm.frombytes(out.stdout[: len(out.stdout) // 2 * 2])
    return pcm


def window_db(pcm: array, rate: int, window: float = 0.05) -> list[float]:
    n = max(1, int(rate * window))
    out = []
    for i in range(0, len(pcm), n):
        chunk = pcm[i:i + n]
        rms = math.sqrt(sum(s * s for s in chunk) / len(chunk)) if chunk else 0
        out.append(20 * math.log10(rms / 32768) if rms > 0 else -96.0)
    return out


def find_spikes(pcm: array, rate: int, window: float = 0.05, jump_db: float = 12.0, floor_db: float = -30.0) -> list[AudioSpike]:
    """Sudden loudness jumps vs the previous second, plus clipped windows."""
    dbs = window_db(pcm, rate, window)
    n = max(1, int(rate * window))
    lookback = int(1 / window)
    spikes: list[AudioSpike] = []
    for i, db in enumerate(dbs):
        t = round(i * window, 2)
        chunk = pcm[i * n:(i + 1) * n]
        clipped = sum(1 for s in chunk if abs(s) >= 32700)
        prev = dbs[max(0, i - lookback):i]
        base = statistics.median(prev) if prev else db
        kind = None
        if clipped >= 3:
            kind = "clip"
        elif db > floor_db and db - base >= jump_db:
            kind = "jump"
        if kind and not (spikes and t - spikes[-1].time < 0.25 and spikes[-1].kind == kind):
            spikes.append(AudioSpike(t, round(db, 1), round(db - base, 1), kind))
    return spikes


def per_second(duration: float, cuts: list[float], pcm: array, rate: int, spikes: list[AudioSpike]) -> list[dict]:
    """One row per second: cuts, loudness, spikes. The timeline the analysis reads."""
    rows = []
    for sec in range(math.ceil(duration)):
        chunk = pcm[sec * rate:(sec + 1) * rate]
        dbs = window_db(chunk, rate) if chunk else [-96.0]
        rows.append({
            "second": sec,
            "cuts": sum(1 for c in cuts if sec <= c < sec + 1),
            "loudness_db": round(statistics.mean(dbs), 1),
            "peak_db": round(max(dbs), 1),
            "spikes": [asdict(s) for s in spikes if sec <= s.time < sec + 1],
        })
    return rows


def _ffmpeg(args: list[str]) -> str:
    out = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-nostats", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise MediaError(out.stderr[-800:])
    return out.stderr
