"""`bada youtube ...` commands."""
from __future__ import annotations

import json
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Edit raw videos and upload them to YouTube as PRIVATE for review.")
console = Console()


def _model(model: str | None) -> str:
    if model:
        return model
    from bada.config import Config

    config = Config.load()
    return config.model if config else "gpt-4o"


def _options(model, language, whisper_model, no_silence, no_retakes, burn_subtitles, no_upload, thumbnail):
    from bada.youtube.pipeline import Options

    return Options(
        model=_model(model), language=language, whisper_model=whisper_model,
        cut_silence=not no_silence, cut_retakes=not no_retakes, burn_subtitles=burn_subtitles,
        upload=not no_upload, thumbnail=thumbnail,
    )


def _report(job: dict) -> None:
    if job.get("video_id"):
        console.print(f"\n[bold green]Uploaded as PRIVATE:[/bold green] {job.get('title', '')}")
        console.print(f"  Watch:  {job['url']}")
        console.print(f"  Studio: {job['studio']}")
        console.print(f"\nCheck it, then publish with: [bold]bada youtube publish {job['video_id']}[/bold]")


@app.command()
def auth(
    client_secret: Path = typer.Option(None, exists=True, help="OAuth client JSON (Desktop app) from Google Cloud"),
    headless: bool = typer.Option(False, help="Don't open a browser automatically; print the URL instead"),
):
    """Connect your YouTube channel (one-time)."""
    from bada.youtube import uploader

    uploader.authorize(client_secret, headless)
    console.print("[green]YouTube connected.[/green]")


@app.command()
def process(
    video: Path = typer.Argument(..., exists=True, dir_okay=False, help="Raw video file"),
    model: str = typer.Option(None, help="LLM for edits and packaging (default: bada config)"),
    language: str = typer.Option("ko", help="Spoken language (whisper + metadata)"),
    whisper_model: str = typer.Option("small", help="tiny/base/small/medium/large-v3"),
    no_silence: bool = typer.Option(False, "--no-silence", help="Don't cut silences"),
    no_retakes: bool = typer.Option(False, "--no-retakes", help="Don't let the LLM cut retakes/filler"),
    burn_subtitles: bool = typer.Option(False, help="Burn subtitles into the video instead of uploading a caption track"),
    no_upload: bool = typer.Option(False, "--no-upload", help="Only produce files locally"),
    thumbnail: Path = typer.Option(None, exists=True, help="Thumbnail image to set"),
):
    """Transcribe, cut, caption, package and upload ONE video as private."""
    from bada.youtube import pipeline

    opts = _options(model, language, whisper_model, no_silence, no_retakes, burn_subtitles, no_upload, thumbnail)
    _report(pipeline.run(video, opts, log=console.print))


def _stable(path: Path, wait: float = 5.0) -> bool:
    """True once the file stops growing (still being copied otherwise)."""
    size = path.stat().st_size
    time.sleep(wait)
    return path.exists() and path.stat().st_size == size and size > 0


@app.command()
def watch(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder to drop raw videos into"),
    interval: int = typer.Option(30, help="Seconds between scans"),
    model: str = typer.Option(None),
    language: str = typer.Option("ko"),
    whisper_model: str = typer.Option("small"),
    no_silence: bool = typer.Option(False, "--no-silence"),
    no_retakes: bool = typer.Option(False, "--no-retakes"),
    burn_subtitles: bool = typer.Option(False),
):
    """Watch a folder: every new video is edited and uploaded as private."""
    from bada.youtube import pipeline

    opts = _options(model, language, whisper_model, no_silence, no_retakes, burn_subtitles, False, None)
    console.print(f"[bold]Watching {folder}[/bold] (Ctrl+C to stop). Uploads stay PRIVATE until you publish.")
    failed: set[Path] = set()
    try:
        while True:
            for video in sorted(folder.iterdir()):
                if video.suffix.lower() not in pipeline.VIDEO_EXTS or video in failed:
                    continue
                if (pipeline.work_dir_for(video) / "job.json").exists():
                    job = json.loads((pipeline.work_dir_for(video) / "job.json").read_text())
                    if job.get("video_id"):
                        continue
                if not _stable(video):
                    continue
                console.rule(video.name)
                try:
                    _report(pipeline.run(video, opts, log=console.print))
                except Exception as e:
                    failed.add(video)
                    console.print(f"[red]Failed: {e}[/red] (won't retry until restart)")
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("Stopped.")


@app.command()
def publish(
    target: str = typer.Argument(..., help="Video id, source video path, or its _bada folder"),
    at: str = typer.Option(None, help="Schedule instead, e.g. 2026-10-10T09:00:00+09:00"),
    unlisted: bool = typer.Option(False, help="Make unlisted instead of public"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
):
    """Make a reviewed video public (or unlisted / scheduled)."""
    from bada.youtube import pipeline, uploader

    job_path, job = pipeline.find_job(target)
    video_id = job.get("video_id")
    if not video_id:
        raise typer.BadParameter(f"No uploaded video found for {target}")
    item = uploader.get_status(video_id)
    title = item["snippet"]["title"]
    privacy = "unlisted" if unlisted else "public"
    what = f"schedule for {at}" if at else f"make {privacy.upper()}"
    if not yes and not typer.confirm(f"{what}: '{title}' (https://youtu.be/{video_id})?"):
        raise typer.Abort()
    uploader.set_privacy(video_id, privacy, publish_at=at)
    if job_path.name == "job.json":
        job.update(privacy="scheduled" if at else privacy, publish_at=at)
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2))
    console.print(f"[green]Done:[/green] {what} -> https://youtu.be/{video_id}")


@app.command()
def status(folder: Path = typer.Argument(Path("."), exists=True, file_okay=False)):
    """List processed videos in a folder and whether they're still private."""
    table = Table("video", "title", "privacy", "link")
    for job_file in sorted(folder.glob("*_bada/job.json")):
        job = json.loads(job_file.read_text())
        table.add_row(Path(job.get("source", "")).name, job.get("title", ""),
                      job.get("privacy", "not uploaded"), job.get("url", job.get("final", "")))
    console.print(table)
