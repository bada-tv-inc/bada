"""Download reels in original quality with yt-dlp (URLs you choose, one at a time)."""
from __future__ import annotations

import json
import time
from pathlib import Path


def _ydl(opts: dict):
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("yt-dlp is not installed. Run: pip install 'bada[reels]'") from e
    return yt_dlp.YoutubeDL(opts)


def fetch(url: str, root: Path, cookies_browser: str | None = None, min_views: int = 0) -> Path | None:
    """Download one reel into root/<id>/. Returns its folder, or None if below `min_views`.

    Original quality: best video + best audio, remuxed without re-encoding.
    """
    base = {"quiet": True, "no_warnings": True}
    if cookies_browser:
        base["cookiesfrombrowser"] = (cookies_browser,)

    with _ydl(base) as ydl:
        info = ydl.extract_info(url, download=False)
    views = info.get("view_count") or info.get("play_count")
    if min_views and views is not None and views < min_views:
        return None

    folder = root / str(info["id"])
    folder.mkdir(parents=True, exist_ok=True)
    meta = {k: info.get(k) for k in (
        "id", "webpage_url", "uploader", "uploader_id", "channel", "title", "description",
        "duration", "view_count", "play_count", "like_count", "comment_count", "timestamp",
        "width", "height", "fps", "track", "artist")}
    meta["views"] = views
    (folder / "info.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    if not (folder / "video.mp4").exists():
        opts = dict(base, format="bv*+ba/b", merge_output_format="mp4", outtmpl=str(folder / "video.%(ext)s"))
        with _ydl(opts) as ydl:
            ydl.download([url])
        time.sleep(3)  # be gentle: one request burst at a time
    return folder
