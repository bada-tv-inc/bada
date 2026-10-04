"""LLM steps: pick segments to cut, and write the YouTube package."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from bada.youtube.timeline import Segment

EDIT_PROMPT = """You are a video editor. Below is a transcript of a raw talking-head recording,
one segment per line as `[id] start-end: text`.

Mark segments to REMOVE:
- retakes: when the speaker restarts or repeats a sentence, remove the earlier, worse attempts and keep the last good one
- false starts and abandoned sentences
- segments that are only filler ("음", "어", "um", "uh", "so yeah") or off-topic asides like "잠깐만 다시 할게"

Be conservative: when unsure, keep it. Never remove content that is said only once.
Reply with JSON only: {"remove": [{"id": <int>, "reason": "<short>"}]}

Transcript:
"""

PACKAGE_PROMPT = """You write YouTube packaging for this video. Language: {language}.
The transcript below is on the FINAL edited timeline, `[mm:ss] text` per line.

Return JSON only:
{{
  "title": "<= 70 characters, specific, no clickbait that the video does not deliver",
  "description": "2-4 short paragraphs, first line hooks in search results. No chapter list, no hashtags.",
  "tags": ["5-15 tags people would actually search"],
  "hashtags": ["up to 3, without #"],
  "chapters": [{{"start": <seconds float>, "title": "<short>"}}],
  "thumbnail_text": "2-5 words for the thumbnail, must not repeat the title"
}}
Chapters: first at 0, at least 10 seconds apart, only where the topic really changes.

Transcript:
"""


@dataclass
class EditDecision:
    removed: list[Segment] = field(default_factory=list)
    reasons: dict[int, str] = field(default_factory=dict)


@dataclass
class Package:
    title: str
    description: str
    tags: list[str]
    hashtags: list[str]
    chapters: list[tuple[float, str]]
    thumbnail_text: str


def _complete(model: str, prompt: str) -> str:
    import litellm

    resp = litellm.completion(model=model, messages=[{"role": "user", "content": prompt}], temperature=0.2)
    return resp.choices[0].message.content or ""


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates ```json fences)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"model did not return JSON: {text[:200]!r}")
    return json.loads(m.group(0))


def _mmss(t: float) -> str:
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


def decide_edits(model: str, segments: list[Segment]) -> EditDecision:
    if not segments:
        return EditDecision()
    lines = "\n".join(f"[{s.id}] {s.start:.1f}-{s.end:.1f}: {s.text}" for s in segments)
    data = parse_json(_complete(model, EDIT_PROMPT + lines))
    by_id = {s.id: s for s in segments}
    decision = EditDecision()
    for item in data.get("remove", []):
        seg = by_id.get(int(item.get("id", -1)))
        if seg is not None and seg.id not in decision.reasons:
            decision.removed.append(seg)
            decision.reasons[seg.id] = str(item.get("reason", ""))
    return decision


def clean_tags(tags: list[str], limit: int = 500) -> list[str]:
    """YouTube rejects tag lists over 500 chars total and tags containing < or >."""
    out, total = [], 0
    for tag in tags:
        tag = re.sub(r"[<>,]", "", str(tag)).strip()
        if not tag or tag in out:
            continue
        cost = len(tag) + (2 if " " in tag else 0) + (1 if out else 0)
        if total + cost > limit:
            break
        out.append(tag)
        total += cost
    return out


def write_package(model: str, segments: list[Segment], language: str) -> Package:
    lines = "\n".join(f"[{_mmss(s.start)}] {s.text}" for s in segments)
    data = parse_json(_complete(model, PACKAGE_PROMPT.format(language=language) + lines))
    title = re.sub(r"[<>]", "", str(data.get("title", "")).strip())[:100] or "Untitled"
    chapters = []
    for c in data.get("chapters", []):
        try:
            chapters.append((float(c["start"]), str(c["title"])))
        except (KeyError, TypeError, ValueError):
            continue
    return Package(
        title=title,
        description=re.sub(r"[<>]", "", str(data.get("description", "")).strip()),
        tags=clean_tags(list(data.get("tags", []))),
        hashtags=[str(h).lstrip("#").replace(" ", "") for h in data.get("hashtags", [])][:3],
        chapters=chapters,
        thumbnail_text=str(data.get("thumbnail_text", "")).strip(),
    )
