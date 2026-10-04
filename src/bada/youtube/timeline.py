"""Pure timeline math: keep-intervals, timestamp remapping, SRT and chapters.

Everything here works in seconds (float) on the *source* video timeline unless
the name says otherwise. No ffmpeg, no network: easy to unit test.
"""
from __future__ import annotations

from dataclasses import dataclass

Interval = tuple[float, float]


@dataclass
class Segment:
    """One transcribed sentence/phrase on the source timeline."""
    id: int
    start: float
    end: float
    text: str


def merge_intervals(intervals: list[Interval], gap: float = 0.0) -> list[Interval]:
    """Sort and merge intervals that overlap or are within `gap` seconds."""
    out: list[Interval] = []
    for start, end in sorted(i for i in intervals if i[1] > i[0]):
        if out and start <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def subtract_intervals(base: list[Interval], remove: list[Interval]) -> list[Interval]:
    """Return `base` with every range in `remove` cut out."""
    result: list[Interval] = []
    remove = merge_intervals(remove)
    for b_start, b_end in merge_intervals(base):
        cursor = b_start
        for r_start, r_end in remove:
            if r_end <= cursor or r_start >= b_end:
                continue
            if r_start > cursor:
                result.append((cursor, r_start))
            cursor = max(cursor, r_end)
        if cursor < b_end:
            result.append((cursor, b_end))
    return result


def build_keep_intervals(
    duration: float,
    silences: list[Interval],
    removed_segments: list[Segment],
    padding: float = 0.15,
    min_keep: float = 0.3,
) -> list[Interval]:
    """Decide which parts of the source survive the edit.

    Silences are shrunk by `padding` on both sides so speech isn't clipped.
    Removed transcript segments (retakes, filler) are cut as-is.
    Keeps shorter than `min_keep` are dropped (they read as glitches).
    """
    cuts: list[Interval] = []
    for s_start, s_end in silences:
        start, end = s_start + padding, s_end - padding
        if end > start:
            cuts.append((start, end))
    cuts.extend((seg.start, seg.end) for seg in removed_segments)
    keeps = subtract_intervals([(0.0, duration)], cuts)
    return [k for k in keeps if k[1] - k[0] >= min_keep]


def remap_time(t: float, keeps: list[Interval]) -> float | None:
    """Map a source timestamp onto the edited timeline (None if it was cut)."""
    offset = 0.0
    for start, end in keeps:
        if t < start:
            return None
        if t <= end:
            return offset + (t - start)
        offset += end - start
    return None


def remap_segment(seg: Segment, keeps: list[Interval]) -> Segment | None:
    """Clip a segment to the kept ranges and map it to the edited timeline."""
    offset = 0.0
    new_start = new_end = None
    for start, end in keeps:
        lo, hi = max(seg.start, start), min(seg.end, end)
        if hi > lo:
            if new_start is None:
                new_start = offset + (lo - start)
            new_end = offset + (hi - start)
        offset += end - start
    if new_start is None or new_end is None:
        return None
    return Segment(seg.id, new_start, new_end, seg.text)


def edited_duration(keeps: list[Interval]) -> float:
    return sum(end - start for start, end in keeps)


def _srt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list[Segment]) -> str:
    blocks = []
    for n, seg in enumerate(segments, 1):
        blocks.append(f"{n}\n{_srt_ts(seg.start)} --> {_srt_ts(seg.end)}\n{seg.text.strip()}\n")
    return "\n".join(blocks)


def format_chapter_ts(t: float) -> str:
    total = int(t)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def validate_chapters(chapters: list[tuple[float, str]], duration: float) -> list[tuple[float, str]]:
    """Coerce chapters into something YouTube will actually render.

    YouTube's rules: first chapter at 0:00, at least 3 chapters, each at least
    10 seconds long, timestamps ascending. Returns [] if that's impossible.
    """
    chapters = sorted((max(0.0, t), title.strip()) for t, title in chapters if title.strip())
    chapters = [(t, title) for t, title in chapters if t < duration]
    if not chapters:
        return []
    chapters[0] = (0.0, chapters[0][1])
    cleaned: list[tuple[float, str]] = []
    for t, title in chapters:
        if cleaned and t - cleaned[-1][0] < 10:
            continue
        cleaned.append((t, title))
    if cleaned and duration - cleaned[-1][0] < 10:
        cleaned.pop()
    return cleaned if len(cleaned) >= 3 else []


def chapters_block(chapters: list[tuple[float, str]]) -> str:
    return "\n".join(f"{format_chapter_ts(t)} {title}" for t, title in chapters)
