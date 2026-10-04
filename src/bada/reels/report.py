"""Roll many analysed reels up into one 'what is working' report."""
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

SYNTH_PROMPT = """Below are element-by-element analyses of {n} viral reels (1M+ views) in our niche.
Our account: {account}
Answer in {language}. Return markdown with:
1. The 3 formulas that repeat most, each with: what it is, which reels use it, a fill-in template.
2. Hook rules backed by the data (first line types, first visual change timing, on-screen text).
3. Pacing rules (cuts per 10s, length, words/s) with the actual numbers.
4. Five concrete reel ideas for our account, each with a first line and the formula it uses.

Data:
{data}
"""


def collect(root: Path) -> list[dict]:
    rows = []
    for folder in sorted(p for p in root.iterdir() if (p / "analysis.json").exists()):
        info = json.loads((folder / "info.json").read_text()) if (folder / "info.json").exists() else {}
        sig = json.loads((folder / "signals.json").read_text())
        ana = json.loads((folder / "analysis.json").read_text())
        rows.append({
            "id": folder.name, "uploader": info.get("uploader"), "views": info.get("views"),
            "url": info.get("webpage_url"), "duration": sig["duration"], "cuts_per_10s": sig["cuts_per_10s"],
            "first_cut": sig["first_cut"], "words_per_second": sig["words_per_second"],
            "hook_type": ana.get("hook", {}).get("type"), "first_line": ana.get("hook", {}).get("first_line"),
            "formula": ana.get("formula"), "template": ana.get("template"),
            "editing": [str(e) for e in ana.get("editing", [])],
        })
    return rows


def summary_table(rows: list[dict]) -> str:
    def med(key):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(statistics.median(vals), 2) if vals else "-"

    out = [
        f"**{len(rows)} reels** · median length {med('duration')}s · median cuts/10s {med('cuts_per_10s')} · "
        f"median first cut {med('first_cut')}s · median words/s {med('words_per_second')}",
        "", "Hook types: " + ", ".join(f"{k} ×{v}" for k, v in Counter(r["hook_type"] for r in rows).most_common()),
        "", "Formulas: " + ", ".join(f"{k} ×{v}" for k, v in Counter(r["formula"] for r in rows).most_common()),
        "", "Editing: " + ", ".join(f"{k} ×{v}" for k, v in Counter(e for r in rows for e in r["editing"]).most_common(10)),
        "", "| reel | views | sec | cuts/10s | hook | formula | first line |", "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: r.get("views") or 0, reverse=True):
        link = f"[{r['uploader'] or r['id']}]({r['url']})" if r.get("url") else r["id"]
        out.append(f"| {link} | {r.get('views') or '?'} | {r['duration']} | {r['cuts_per_10s']} | "
                   f"{r['hook_type']} | {r['formula']} | {(r['first_line'] or '').replace('|', '/')} |")
    return "\n".join(out)


def build(root: Path, model: str, account: str, language: str = "Korean") -> Path:
    import litellm

    rows = collect(root)
    if not rows:
        raise RuntimeError(f"No analysed reels in {root}. Run `bada reels analyze` first.")
    synthesis = litellm.completion(model=model, temperature=0.3, messages=[{"role": "user", "content": SYNTH_PROMPT.format(
        n=len(rows), account=account or "(not specified)", language=language,
        data=json.dumps(rows, ensure_ascii=False))}]).choices[0].message.content
    path = root / "REPORT.md"
    path.write_text(f"# Viral reels report\n\n{summary_table(rows)}\n\n---\n\n{synthesis}\n")
    return path
