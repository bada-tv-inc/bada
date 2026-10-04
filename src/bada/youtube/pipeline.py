"""Glue: raw video in, private YouTube upload (plus local artefacts) out."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from bada.youtube import media, timeline
from bada.youtube.timeline import Segment

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}


@dataclass
class Options:
    model: str
    language: str = "ko"
    whisper_model: str = "small"
    cut_silence: bool = True
    cut_retakes: bool = True
    min_silence: float = 0.8
    noise_db: float = -35.0
    burn_subtitles: bool = False
    upload: bool = True
    thumbnail: Path | None = None


def work_dir_for(video: Path) -> Path:
    return video.parent / f"{video.stem}_bada"


def _load_segments(path: Path) -> list[Segment]:
    return [Segment(**s) for s in json.loads(path.read_text())]


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def run(video: Path, opts: Options, log: Callable[[str], None] = print) -> dict:
    """Process one video. Returns the job record (also written to job.json)."""
    from bada.youtube import llm, transcribe

    media.require_ffmpeg()
    video = video.resolve()
    work = work_dir_for(video)
    work.mkdir(exist_ok=True)
    job_path = work / "job.json"
    job = json.loads(job_path.read_text()) if job_path.exists() else {"source": str(video)}

    if job.get("video_id"):
        log(f"Already uploaded as {job['video_id']} (private). Skipping. Delete {job_path} to redo.")
        return job

    duration = media.probe_duration(video)

    # 1. Transcript (cached: it is the slow step)
    transcript_path = work / "transcript.json"
    if transcript_path.exists():
        segments = _load_segments(transcript_path)
        log(f"1/5 Transcript: reusing {len(segments)} segments")
    else:
        log(f"1/5 Transcribing with whisper-{opts.whisper_model} ...")
        segments = transcribe.transcribe(video, opts.whisper_model, opts.language)
        _save_json(transcript_path, [asdict(s) for s in segments])
        log(f"    {len(segments)} segments")

    # 2. Edit decisions
    log("2/5 Deciding cuts ...")
    silences = media.detect_silences(video, duration, opts.noise_db, opts.min_silence) if opts.cut_silence else []
    decision = llm.decide_edits(opts.model, segments) if opts.cut_retakes else llm.EditDecision()
    keeps = timeline.build_keep_intervals(duration, silences, decision.removed)
    final_len = timeline.edited_duration(keeps)
    _save_json(work / "edits.json", {
        "silences": silences,
        "removed": [{"id": s.id, "start": s.start, "end": s.end, "text": s.text,
                     "reason": decision.reasons.get(s.id, "")} for s in decision.removed],
        "keep": keeps,
        "duration_before": duration, "duration_after": final_len,
    })
    log(f"    {len(silences)} silences, {len(decision.removed)} retakes/fillers -> "
        f"{timeline.format_chapter_ts(duration)} => {timeline.format_chapter_ts(final_len)}")

    # 3. Captions on the edited timeline
    edited_segments = [s for s in (timeline.remap_segment(seg, keeps) for seg in segments
                                   if seg.id not in decision.reasons) if s is not None]
    srt_path = work / "captions.srt"
    srt_path.write_text(timeline.to_srt(edited_segments))

    # 4. Render
    final_path = work / "final.mp4"
    log("3/5 Rendering edited video (ffmpeg) ...")
    media.render_cut(video, final_path, keeps, burn_srt=srt_path if opts.burn_subtitles else None)

    # 5. Packaging
    log("4/5 Writing title / description / tags / chapters ...")
    package = llm.write_package(opts.model, edited_segments, opts.language)
    chapters = timeline.validate_chapters(package.chapters, final_len)
    description = package.description
    if chapters:
        description += "\n\n" + timeline.chapters_block(chapters)
    if package.hashtags:
        description += "\n\n" + " ".join(f"#{h}" for h in package.hashtags)
    description = description[:5000]
    _save_json(work / "package.json", {
        "title": package.title, "description": description, "tags": package.tags,
        "chapters": chapters, "thumbnail_text": package.thumbnail_text,
    })
    job.update(title=package.title, final=str(final_path))

    if not opts.upload:
        log(f"5/5 Upload skipped. Everything is in {work}")
        _save_json(job_path, job)
        return job

    # 6. Private upload - publishing is always a separate, manual step
    from bada.youtube import uploader

    log("5/5 Uploading as PRIVATE ...")
    video_id = uploader.upload_private(
        final_path, package.title, description, package.tags, language=opts.language,
        progress=lambda p: log(f"    {p:.0%}"),
    )
    job.update(video_id=video_id, privacy="private", url=f"https://youtu.be/{video_id}",
               studio=f"https://studio.youtube.com/video/{video_id}/edit")
    _save_json(job_path, job)  # save before optional extras so a failure there doesn't cause a re-upload

    if edited_segments and not opts.burn_subtitles:
        try:
            uploader.upload_captions(video_id, srt_path, opts.language)
        except Exception as e:  # captions are nice-to-have
            log(f"    captions upload failed ({e}); captions.srt is in {work}")
    if opts.thumbnail:
        try:
            uploader.upload_thumbnail(video_id, opts.thumbnail)
        except Exception as e:  # needs a verified channel
            log(f"    thumbnail upload failed ({e}); set it in Studio instead")

    return job


def find_job(target: str) -> tuple[Path, dict]:
    """Resolve a video id, source video path, or work dir to its job.json."""
    p = Path(target)
    for candidate in (p / "job.json", work_dir_for(p) / "job.json", p):
        if candidate.is_file() and candidate.name == "job.json":
            return candidate, json.loads(candidate.read_text())
    return Path(), {"video_id": target}
