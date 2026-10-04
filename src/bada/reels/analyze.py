"""Run every signal on one reel and ask a vision LLM to break it into elements."""
from __future__ import annotations

import base64
import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from bada.reels import signals
from bada.youtube import media

ELEMENT_PROMPT = """You are analysing a viral short-form video (Instagram Reel) so a creator can learn from it.
Answer in {language}. Use the measured data; don't invent numbers.

Account we're learning FOR: {account}

Metadata: {meta}

Transcript, one sentence per line `[start-end] text`:
{transcript}

Per-second timeline (cuts = hard cuts in that second, loudness in dBFS, spikes = sudden loud moments/clipping):
{timeline}

The attached image is a contact sheet of the first 3 seconds: 24 frames, one every 0.125s,
left-to-right then top-to-bottom (row 1 = 0.000-0.625s, row 2 = 0.750-1.375s, ...).

Return JSON only:
{{
  "hook": {{
    "first_line": "exact first spoken sentence (or 'none')",
    "type": "one of: question, bold_claim, direct_address, result_first, pattern_interrupt, curiosity_gap, conflict, list_promise, visual_only, other",
    "visual": "what is on screen in 0-1s and what changes by 3s (cite frame times)",
    "on_screen_text": "any text overlay visible in the frames",
    "first_change_at": "seconds of the first visual change/cut in the sheet",
    "why_it_stops_the_scroll": "1-2 sentences"
  }},
  "structure": [{{"start": 0.0, "end": 0.0, "role": "hook|setup|value|twist|payoff|cta|loop", "summary": "..."}}],
  "pacing": "describe cut rhythm and where it speeds up/slows down, from the timeline",
  "audio": "voice/music/sfx and what the spikes are used for (emphasis? transitions? mistakes?)",
  "retention_devices": ["open loops, numbered lists, payoffs delayed, captions, zooms, ..."],
  "content_format": "one line, e.g. 'viral original full-screen first -> kinetic captions on a plain background'",
  "editing": ["concrete edit techniques seen, e.g. 'Pop Up', 'PIP center 30%', 'whoosh SFX', 'black canvas', 'one-word captions'"],
  "cta": "how it asks for follow/save/comment/share (comment keyword?), and where",
  "formula": "a 2-4 word name for the reusable pattern",
  "template": "fill-in-the-blank version of the script structure",
  "apply_to_our_account": "one concrete reel idea for our account using this formula"
}}
"""


def _sheet_message(sheet: Path, text: str) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": text}]
    if sheet.exists():
        b64 = base64.b64encode(sheet.read_bytes()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    return [{"role": "user", "content": content}]


def find_video(folder: Path) -> Path:
    for ext in ("mp4", "mov", "mkv", "webm"):
        if (folder / f"video.{ext}").exists():
            return folder / f"video.{ext}"
    raise FileNotFoundError(f"No video.* in {folder}")


def extract(folder: Path, whisper_model: str = "small", language: str | None = "ko",
            log: Callable[[str], None] = print) -> dict:
    """All the measurable signals. Cached per step in the folder."""
    from bada.youtube import transcribe

    media.require_ffmpeg()
    video = find_video(folder)
    duration = media.probe_duration(video)

    sentences_path = folder / "transcript.json"
    if sentences_path.exists():
        sentences = json.loads(sentences_path.read_text())
    else:
        log("  transcribing (sentence level) ...")
        words = transcribe.transcribe_words(video, whisper_model, language) if media.has_audio(video) else []
        sentences = [asdict(s) for s in signals.group_sentences(words)]
        sentences_path.write_text(json.dumps(sentences, ensure_ascii=False, indent=2))

    log("  first 3s frames (every 0.125s) ...")
    frames = signals.extract_hook_frames(video, folder / "hook_frames")

    log("  cuts and audio spikes ...")
    cuts = signals.detect_cuts(video)
    rate = 8000
    pcm = signals.read_pcm(video, rate)
    spikes = signals.find_spikes(pcm, rate)
    timeline = signals.per_second(duration, cuts, pcm, rate, spikes)

    data = {
        "duration": round(duration, 2),
        "hook_frames": len(frames),
        "cuts": cuts,
        "cuts_per_10s": round(len(cuts) / duration * 10, 2) if duration else 0,
        "first_cut": cuts[0] if cuts else None,
        "spikes": [asdict(s) for s in spikes],
        "timeline": timeline,
        "sentences": sentences,
        "words_per_second": round(sum(len(s["text"].split()) for s in sentences) / duration, 2) if duration else 0,
    }
    (folder / "signals.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def analyze_elements(folder: Path, data: dict, model: str, account: str, language: str = "Korean") -> dict:
    import litellm

    from bada.youtube.llm import parse_json

    meta = json.loads((folder / "info.json").read_text()) if (folder / "info.json").exists() else {}
    meta = {k: meta.get(k) for k in ("uploader", "views", "like_count", "comment_count", "description", "track")}
    transcript = "\n".join(f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in data["sentences"]) or "(no speech)"
    timeline = "\n".join(
        f"{r['second']:>3}s cuts={r['cuts']} loud={r['loudness_db']} peak={r['peak_db']}"
        + (f" spikes={[(s['time'], s['kind']) for s in r['spikes']]}" if r["spikes"] else "")
        for r in data["timeline"])
    prompt = ELEMENT_PROMPT.format(language=language, account=account or "(not specified)",
                                   meta=json.dumps(meta, ensure_ascii=False), transcript=transcript, timeline=timeline)
    resp = litellm.completion(model=model, messages=_sheet_message(folder / "hook_frames" / "sheet.jpg", prompt),
                              temperature=0.2)
    result = parse_json(resp.choices[0].message.content or "")
    (folder / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (folder / "analysis.md").write_text(render_markdown(meta, data, result))
    return result


def render_markdown(meta: dict, data: dict, a: dict) -> str:
    hook = a.get("hook", {})
    lines = [
        f"# {meta.get('uploader') or ''} · {meta.get('views') or '?'} views",
        f"**Formula:** {a.get('formula', '')}  ",
        f"**Length:** {data['duration']}s · **cuts/10s:** {data['cuts_per_10s']} · "
        f"**first cut:** {data['first_cut']}s · **words/s:** {data['words_per_second']}",
        "", "## Hook (0-3s)",
        f"- First line: {hook.get('first_line', '')}",
        f"- Type: {hook.get('type', '')}",
        f"- Visual: {hook.get('visual', '')}",
        f"- On-screen text: {hook.get('on_screen_text', '')}",
        f"- Why it works: {hook.get('why_it_stops_the_scroll', '')}",
        "", "## Structure",
        *[f"- {s.get('start')}–{s.get('end')}s **{s.get('role')}**: {s.get('summary')}" for s in a.get("structure", [])],
        "", f"## Format\n{a.get('content_format', '')}",
        "", "## Editing", *[f"- {e}" for e in a.get("editing", [])],
        "", f"## Pacing\n{a.get('pacing', '')}",
        "", f"## Audio\n{a.get('audio', '')}",
        "", "## Retention devices", *[f"- {d}" for d in a.get("retention_devices", [])],
        "", f"## CTA\n{a.get('cta', '')}",
        "", f"## Template\n{a.get('template', '')}",
        "", f"## For our account\n{a.get('apply_to_our_account', '')}",
        "", "## Transcript",
        *[f"- `{s['start']:.2f}` {s['text']}" for s in data["sentences"]],
    ]
    return "\n".join(lines) + "\n"
