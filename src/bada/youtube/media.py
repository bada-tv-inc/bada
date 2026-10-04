"""ffmpeg / ffprobe wrappers: probe, silence detection, rendering the cut."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from bada.youtube.timeline import Interval


class MediaError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise MediaError(f"{tool} not found. Install it (e.g. `sudo apt install ffmpeg` or `brew install ffmpeg`).")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise MediaError(f"ffprobe failed on {path}: {out.stderr.strip()}")
    return float(json.loads(out.stdout)["format"]["duration"])


_SIL_START = re.compile(r"silence_start: (-?[\d.]+)")
_SIL_END = re.compile(r"silence_end: (-?[\d.]+)")


def parse_silencedetect(stderr: str, duration: float) -> list[Interval]:
    silences: list[Interval] = []
    start: float | None = None
    for line in stderr.splitlines():
        if m := _SIL_START.search(line):
            start = max(0.0, float(m.group(1)))
        elif (m := _SIL_END.search(line)) and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None:  # silence runs to the end of the file
        silences.append((start, duration))
    return silences


def detect_silences(path: Path, duration: float, noise_db: float = -35.0, min_silence: float = 0.8) -> list[Interval]:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise MediaError(f"silence detection failed: {out.stderr[-500:]}")
    return parse_silencedetect(out.stderr, duration)


def has_audio(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


def build_select_filter(keeps: list[Interval], audio: bool) -> str:
    expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in keeps)
    graph = f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v]"
    if audio:
        graph += f";[0:a]aselect='{expr}',asetpts=N/SR/TB[a]"
    return graph


def render_cut(src: Path, dst: Path, keeps: list[Interval], burn_srt: Path | None = None) -> None:
    """Re-encode `src` keeping only `keeps`. Optionally burn subtitles in."""
    if not keeps:
        raise MediaError("Nothing left to keep after editing.")
    audio = has_audio(src)
    graph = build_select_filter(keeps, audio)
    if burn_srt is not None:
        escaped = str(burn_srt.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        graph = graph.replace("[v]", "[vcut]", 1) + f";[vcut]subtitles='{escaped}'[v]"
    script = dst.with_suffix(".filter.txt")
    script.write_text(graph)  # long cut lists overflow the command line otherwise
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
           "-filter_complex_script", str(script), "-map", "[v]"]
    if audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(dst)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise MediaError(f"render failed: {out.stderr[-1000:]}")
    script.unlink(missing_ok=True)
