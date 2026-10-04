"""Turn our raw video into a reel that follows a formula learned from viral reels.

plan (LLM picks and orders clips from our transcript to fit the formula)
  -> render each clip 1080x1920 (full-screen or on a black canvas, optional pop-up zoom)
  -> concat -> one-word kinetic captions + headlines + comment-keyword CTA (ASS)
  -> whoosh SFX on every cut.
"""
from __future__ import annotations

import json
import statistics
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from bada.youtube.media import MediaError, has_audio, probe_duration, require_ffmpeg

W, H, FPS = 1080, 1920, 30

DEFAULT_FORMULA = {
    "formula": "결과 먼저 → 왜 됐을까",
    "template": "0-3s 가장 강한 결과/장면 먼저 · 3-8s '이게 왜 됐을까?' 질문 · 중간: 패턴 깨기 + 근거 · "
                "정리 한 줄 · 끝 5s 댓글 키워드 CTA",
}

PLAN_PROMPT = """You are editing a short vertical reel (Instagram) from OUR raw video.
Account: {account}

Formulas that made 1M+ view reels in our niche (most common first):
{formulas}
Measured on those reels: median length {length}s, median {cuts} cuts per 10s.

Our transcript, one sentence per line `[start-end] text` (seconds in OUR raw video):
{transcript}

Build the reel by choosing clips from our video. Rules:
- Pick the ONE formula that fits our material best.
- Clips may be reordered: put the strongest result/claim FIRST (0-3s), even if it comes late in the raw video.
- Start and end clips on sentence boundaries from the transcript. Each clip >= 1s.
- Total length about {length}s (never over 90s). Cut often enough to match the rhythm above.
- layout: "full" (face full screen) or "canvas" (video smaller on a black canvas, headline text above) - alternate
  them to break the pattern, like the viral reels do.
- pop: true for a punch-in zoom at the clip start (use on the hook and on surprising lines).
- headline: <= 12 characters of on-screen text for that clip, or "".
- End with a CTA asking for a comment keyword.

Return JSON only:
{{
  "formula": "...",
  "why": "one sentence",
  "clips": [{{"start": 0.0, "end": 0.0, "role": "hook|preview|pattern_break|proof|summary|cta", "layout": "full|canvas", "pop": false, "headline": ""}}],
  "cta_keyword": "one word people comment",
  "cta_text": "short on-screen CTA line using the keyword",
  "caption": "Instagram caption, 2-4 lines, ends with the comment-keyword ask",
  "hashtags": ["up to 5, without #"]
}}
"""


@dataclass
class Clip:
    start: float
    end: float
    role: str = ""
    layout: str = "full"
    pop: bool = False
    headline: str = ""


@dataclass
class Plan:
    clips: list[Clip]
    formula: str = ""
    why: str = ""
    cta_keyword: str = ""
    cta_text: str = ""
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)


# ---------- research -> formulas ----------

def load_research(root: Path | None) -> tuple[str, float, float]:
    """(formula text, median length, median cuts/10s) from analysed reels, or built-in defaults."""
    if not root or not root.exists():
        return f"- {DEFAULT_FORMULA['formula']}: {DEFAULT_FORMULA['template']}", 30.0, 4.0
    from collections import Counter

    formulas: Counter = Counter()
    templates: dict[str, str] = {}
    lengths, cuts = [], []
    for folder in root.iterdir():
        if not (folder / "analysis.json").exists():
            continue
        a = json.loads((folder / "analysis.json").read_text())
        s = json.loads((folder / "signals.json").read_text())
        name = a.get("formula") or "?"
        formulas[name] += 1
        templates.setdefault(name, a.get("template", ""))
        lengths.append(s["duration"])
        cuts.append(s["cuts_per_10s"])
    if not formulas:
        return load_research(None)
    text = "\n".join(f"- {name} (x{n}): {templates[name]}" for name, n in formulas.most_common(6))
    return text, round(statistics.median(lengths), 1), round(statistics.median(cuts), 1)


# ---------- plan ----------

def validate_plan(raw: dict, duration: float, max_total: float = 90.0) -> Plan:
    clips: list[Clip] = []
    total = 0.0
    for c in raw.get("clips", []):
        try:
            start, end = max(0.0, float(c["start"])), min(duration, float(c["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        if end - start < 0.5:
            continue
        if total + (end - start) > max_total:
            end = start + (max_total - total)
            if end - start < 0.5:
                break
        clips.append(Clip(start, end, str(c.get("role", "")),
                          "canvas" if c.get("layout") == "canvas" else "full",
                          bool(c.get("pop")), str(c.get("headline", ""))[:20]))
        total += end - start
    if not clips:
        raise ValueError("Plan has no usable clips.")
    return Plan(clips, str(raw.get("formula", "")), str(raw.get("why", "")), str(raw.get("cta_keyword", "")),
                str(raw.get("cta_text", "")), str(raw.get("caption", "")),
                [str(h).lstrip("#") for h in raw.get("hashtags", [])][:5])


def make_plan(model: str, sentences: list[dict], duration: float, account: str, research: Path | None) -> Plan:
    import litellm

    from bada.youtube.llm import parse_json

    formulas, length, cuts = load_research(research)
    transcript = "\n".join(f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in sentences)
    prompt = PLAN_PROMPT.format(account=account, formulas=formulas, length=length, cuts=cuts, transcript=transcript)
    resp = litellm.completion(model=model, temperature=0.3, messages=[{"role": "user", "content": prompt}])
    return validate_plan(parse_json(resp.choices[0].message.content or ""), duration)


# ---------- captions (ASS) ----------

def clip_offsets(clips: list[Clip]) -> list[float]:
    out, t = [], 0.0
    for c in clips:
        out.append(t)
        t += c.end - c.start
    return out


def words_on_reel(words: list[tuple[float, float, str]], clips: list[Clip]) -> list[tuple[float, float, str]]:
    """Map raw-video words onto the reel timeline, clip by clip (clips can be reordered)."""
    out = []
    for offset, c in zip(clip_offsets(clips), clips):
        for ws, we, text in words:
            mid = (ws + we) / 2
            if c.start <= mid < c.end:
                s = offset + max(0.0, ws - c.start)
                e = offset + min(c.end, we) - c.start
                out.append((round(s, 3), round(max(e, s + 0.12), 3), text.strip()))
    return out


def _ass_ts(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_ass(words: list[tuple[float, float, str]], plan: Plan, total: float, font: str) -> str:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{font},120,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,8,0,2,60,60,420,1
Style: Headline,{font},92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,6,0,8,60,60,260,1
Style: CTA,{font},84,&H00FFFFFF,&H00FFFFFF,&H00256BE8,&H00256BE8,-1,0,0,0,100,100,0,0,3,24,0,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    pop = r"{\fscx130\fscy130\t(0,90,\fscx100\fscy100)}"
    for i, (s, e, text) in enumerate(words):
        nxt = words[i + 1][0] if i + 1 < len(words) else e
        end = max(e, min(nxt, s + 1.2)) if nxt > s else e
        events.append(f"Dialogue: 1,{_ass_ts(s)},{_ass_ts(end)},Word,,0,0,0,,{pop}{_ass_text(text)}")
    for offset, c in zip(clip_offsets(plan.clips), plan.clips):
        if c.headline:
            events.append(f"Dialogue: 2,{_ass_ts(offset)},{_ass_ts(offset + c.end - c.start)},Headline,,0,0,0,,"
                          f"{pop}{_ass_text(c.headline)}")
    if plan.cta_text:
        start = max(0.0, total - 3.0)
        events.append(f"Dialogue: 3,{_ass_ts(start)},{_ass_ts(total)},CTA,,0,0,0,,{pop}{_ass_text(plan.cta_text)}")
    return header + "\n".join(events) + "\n"


# ---------- render ----------

def layout_filter(clip: Clip, canvas_scale: float = 0.62) -> str:
    if clip.layout == "canvas":
        w, h = int(W * canvas_scale) // 2 * 2, int(H * canvas_scale) // 2 * 2
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black")
    else:
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    if clip.pop:
        # punch-in: start 18% zoomed, settle to 100% over 0.3s
        vf += (f",scale=w='trunc({W}*max(1,1.18-0.6*t)/2)*2':h='trunc({H}*max(1,1.18-0.6*t)/2)*2'"
               f":eval=frame,crop={W}:{H}")
    return vf + f",fps={FPS},setsar=1,format=yuv420p"


def _run(cmd: list[str]) -> None:
    out = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *cmd], capture_output=True, text=True)
    if out.returncode != 0:
        raise MediaError(out.stderr[-1200:])


def render(video: Path, plan: Plan, words: list[tuple[float, float, str]], work: Path,
           font: str = "Noto Sans CJK KR", sfx: bool = True, log: Callable[[str], None] = print) -> Path:
    require_ffmpeg()
    parts = work / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    audio = has_audio(video)
    listing = []
    for i, c in enumerate(plan.clips):
        log(f"  clip {i + 1}/{len(plan.clips)} {c.start:.1f}-{c.end:.1f}s {c.role} [{c.layout}{' pop' if c.pop else ''}]")
        part = parts / f"{i:02d}.mp4"
        cmd = ["-ss", f"{c.start:.3f}", "-to", f"{c.end:.3f}", "-i", str(video)]
        if not audio:
            cmd += ["-f", "lavfi", "-t", f"{c.end - c.start:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        cmd += ["-vf", layout_filter(c), "-map", "0:v", "-map", "0:a" if audio else "1:a",
                "-af", "aresample=48000,aformat=channel_layouts=stereo",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(part)]
        _run(cmd)
        listing.append(f"file '{part.resolve()}'")
    concat_list = parts / "list.txt"
    concat_list.write_text("\n".join(listing) + "\n")
    joined = parts / "joined.mp4"
    _run(["-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(joined)])

    total = probe_duration(joined)
    ass = work / "captions.ass"
    ass.write_text(build_ass(words_on_reel(words, plan.clips), plan, total, font))
    escaped = str(ass.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

    out = work / "reel.mp4"
    boundaries = clip_offsets(plan.clips)[1:]
    if sfx and boundaries:
        whoosh = parts / "whoosh.wav"
        _run(["-f", "lavfi", "-i", "anoisesrc=d=0.4:c=pink:a=0.6", "-af",
              "highpass=f=400,lowpass=f=5000,afade=t=in:d=0.18,afade=t=out:st=0.18:d=0.22", str(whoosh)])
        n = len(boundaries)
        graph = f"[1:a]asplit={n}" + "".join(f"[w{i}]" for i in range(n)) + ";" if n > 1 else "[1:a]anull[w0];"
        for i, t in enumerate(boundaries):
            ms = max(0, int((t - 0.2) * 1000))
            graph += f"[w{i}]adelay={ms}|{ms},volume=0.5[d{i}];"
        graph += "[0:a]" + "".join(f"[d{i}]" for i in range(n)) + f"amix=inputs={n + 1}:normalize=0:duration=first[a];"
        graph += f"[0:v]ass='{escaped}'[v]"
        _run(["-i", str(joined), "-i", str(whoosh), "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
              "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
              "-movflags", "+faststart", str(out)])
    else:
        _run(["-i", str(joined), "-vf", f"ass='{escaped}'", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
              "-c:a", "copy", "-movflags", "+faststart", str(out)])
    return out


# ---------- glue ----------

def run(video: Path, model: str | None, account: str, research: Path | None, plan_file: Path | None = None,
        plan_only: bool = False, font: str = "Noto Sans CJK KR", sfx: bool = True, whisper_model: str = "small",
        language: str = "ko", log: Callable[[str], None] = print) -> Path:
    from bada.reels.signals import group_sentences
    from bada.youtube import transcribe

    video = video.resolve()
    work = video.parent / f"{video.stem}_reel"
    work.mkdir(exist_ok=True)
    words_path = work / "words.json"
    if words_path.exists():
        words = [tuple(w) for w in json.loads(words_path.read_text())]
    else:
        log("1/3 Transcribing (word level) ...")
        words = transcribe.transcribe_words(video, whisper_model, language)
        words_path.write_text(json.dumps(words, ensure_ascii=False))
    sentences = [asdict(s) for s in group_sentences(words)]
    duration = probe_duration(video)

    plan_path = work / "plan.json"
    if plan_file:
        plan = validate_plan(json.loads(plan_file.read_text()), duration)
        log(f"2/3 Using plan from {plan_file}")
    else:
        log("2/3 Planning the reel from the viral formulas ...")
        plan = make_plan(model, sentences, duration, account, research)
    plan_path.write_text(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
    log(f"    formula: {plan.formula} - {plan.why}")
    caption = plan.caption + ("\n\n" + " ".join(f"#{h}" for h in plan.hashtags) if plan.hashtags else "")
    (work / "caption.txt").write_text(caption.strip() + "\n")
    if plan_only:
        log(f"Plan written to {plan_path}. Edit it, then: bada reels make {video.name} --plan {plan_path}")
        return plan_path

    log("3/3 Rendering 1080x1920 ...")
    return render(video, plan, words, work, font, sfx, log)
