"""`bada reels ...` commands."""
from __future__ import annotations

import shutil
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Collect viral reels and break down why they work.")
console = Console()

DEFAULT_OUT = Path("reels_research")


def _model(model: str | None) -> str:
    from bada.youtube.cli import _model as resolve

    return resolve(model)


def _targets(items: list[str], urls_file: Path | None) -> list[str]:
    targets = list(items or [])
    if urls_file:
        targets += [l.strip() for l in urls_file.read_text().splitlines() if l.strip() and not l.startswith("#")]
    return targets


def _import_local(path: Path, out: Path) -> Path:
    folder = out / path.stem
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / f"video{path.suffix.lower()}"
    if not dst.exists():
        shutil.copy2(path, dst)
    return folder


@app.command()
def analyze(
    items: list[str] = typer.Argument(None, help="Reel URLs and/or local video files"),
    urls: Path = typer.Option(None, exists=True, help="Text file with one URL per line"),
    out: Path = typer.Option(DEFAULT_OUT, help="Research folder"),
    min_views: int = typer.Option(1_000_000, help="Skip reels with fewer views (when the count is known)"),
    cookies_browser: str = typer.Option(None, help="Use this browser's cookies for yt-dlp (chrome/firefox/safari). "
                                                   "Use a throwaway account, never the one you manage."),
    account: str = typer.Option("@bighugorg", help="Our account and niche, so ideas are tailored"),
    model: str = typer.Option(None, help="Vision-capable LLM (default: bada config)"),
    language: str = typer.Option("ko", help="Spoken language for whisper"),
    whisper_model: str = typer.Option("small"),
    signals_only: bool = typer.Option(False, "--signals-only", help="Measure only, skip the LLM breakdown"),
):
    """Download (original quality) -> sentences -> first-3s frames -> cuts/spikes -> element analysis."""
    from bada.reels import analyze as az
    from bada.reels import fetch

    targets = _targets(items, urls)
    if not targets:
        raise typer.BadParameter("Give reel URLs, video files, or --urls file.txt")
    out.mkdir(parents=True, exist_ok=True)
    llm_model = None if signals_only else _model(model)
    done = skipped = failed = 0
    for target in targets:
        console.rule(target)
        try:
            if Path(target).is_file():
                folder = _import_local(Path(target), out)
            else:
                folder = fetch.fetch(target, out, cookies_browser, min_views)
                if folder is None:
                    console.print(f"[yellow]  under {min_views:,} views, skipped[/yellow]")
                    skipped += 1
                    continue
            data = az.extract(folder, whisper_model, language, log=console.print)
            console.print(f"  {data['duration']}s · {len(data['cuts'])} cuts · {len(data['spikes'])} spikes · "
                          f"{len(data['sentences'])} sentences · {data['hook_frames']} hook frames")
            if llm_model:
                result = az.analyze_elements(folder, data, llm_model, account)
                console.print(f"  [green]formula:[/green] {result.get('formula')}  -> {folder / 'analysis.md'}")
            done += 1
        except Exception as e:
            failed += 1
            console.print(f"[red]  failed: {e}[/red]")
    console.print(f"\n[bold]{done} analysed, {skipped} skipped, {failed} failed[/bold] in {out}")
    if done and not signals_only:
        console.print(f"Next: [bold]bada reels report --out {out}[/bold]")


@app.command()
def report(
    out: Path = typer.Option(DEFAULT_OUT, exists=True, file_okay=False),
    account: str = typer.Option("@bighugorg"),
    model: str = typer.Option(None),
):
    """Combine all analysed reels into REPORT.md: repeating formulas, hook and pacing rules, ideas."""
    from bada.reels import report as rp

    path = rp.build(out, _model(model), account)
    console.print(f"[green]Report:[/green] {path}")


@app.command()
def make(
    video: Path = typer.Argument(..., exists=True, dir_okay=False, help="Our raw video"),
    research: Path = typer.Option(DEFAULT_OUT, help="Folder analysed with `bada reels analyze` (formulas to follow)"),
    account: str = typer.Option("@bighugorg"),
    model: str = typer.Option(None),
    plan: Path = typer.Option(None, exists=True, help="Render from an edited plan.json instead of asking the LLM"),
    plan_only: bool = typer.Option(False, "--plan-only", help="Write plan.json and stop, so you can edit it"),
    font: str = typer.Option("Noto Sans CJK KR", help="Caption font (must support Korean)"),
    no_sfx: bool = typer.Option(False, "--no-sfx", help="No whoosh on cuts"),
    language: str = typer.Option("ko"),
    whisper_model: str = typer.Option("small"),
):
    """Make a 1080x1920 reel from OUR video, following the viral formulas found in research."""
    from bada.reels import make as mk

    out = mk.run(video, None if plan else _model(model), account, research, plan_file=plan, plan_only=plan_only,
                 font=font, sfx=not no_sfx, whisper_model=whisper_model, language=language, log=console.print)
    if out.suffix == ".mp4":
        console.print(f"\n[bold green]Reel:[/bold green] {out}")
        console.print(f"Caption: {out.parent / 'caption.txt'}")
        console.print(f"Not happy with a cut? Edit {out.parent / 'plan.json'} and run with --plan to re-render.")
