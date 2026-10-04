"""YouTube Data API v3: OAuth, private upload, captions, publish after review."""
from __future__ import annotations

from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
CONFIG_DIR = Path.home() / ".config" / "bada" / "youtube"
CLIENT_SECRET = CONFIG_DIR / "client_secret.json"
TOKEN = CONFIG_DIR / "token.json"


def _imports():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as e:
        raise RuntimeError("Google API libraries missing. Run: pip install 'bada[youtube]'") from e
    return Request, Credentials, InstalledAppFlow, build, MediaFileUpload


def authorize(client_secret: Path | None = None, headless: bool = False):
    """Run (or refresh) the OAuth flow and cache the token."""
    Request, Credentials, InstalledAppFlow, _, _ = _imports()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        secret = client_secret or CLIENT_SECRET
        if not secret.exists():
            raise RuntimeError(
                f"OAuth client file not found at {secret}. Create a 'Desktop app' OAuth client in Google Cloud "
                "Console (YouTube Data API v3 enabled), download the JSON, and run `bada youtube auth --client-secret <file>`."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=not headless)
        if secret != CLIENT_SECRET:
            CLIENT_SECRET.write_bytes(secret.read_bytes())
    TOKEN.write_text(creds.to_json())
    TOKEN.chmod(0o600)
    return creds


def _service():
    _, _, _, build, _ = _imports()
    return build("youtube", "v3", credentials=authorize(), cache_discovery=False)


def upload_private(video: Path, title: str, description: str, tags: list[str],
                   category_id: str = "22", language: str = "ko", progress=None) -> str:
    """Upload as PRIVATE. Returns the video id. Never publishes."""
    _, _, _, _, MediaFileUpload = _imports()
    body = {
        "snippet": {
            "title": title, "description": description, "tags": tags,
            "categoryId": category_id, "defaultLanguage": language, "defaultAudioLanguage": language,
        },
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = _service().videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress:
            progress(status.progress())
    return response["id"]


def upload_captions(video_id: str, srt: Path, language: str = "ko", name: str = "") -> None:
    _, _, _, _, MediaFileUpload = _imports()
    _service().captions().insert(
        part="snippet",
        body={"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": False}},
        media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream"),
    ).execute()


def upload_thumbnail(video_id: str, image: Path) -> None:
    _, _, _, _, MediaFileUpload = _imports()
    _service().thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(image))).execute()


def get_status(video_id: str) -> dict:
    items = _service().videos().list(part="status,snippet", id=video_id).execute().get("items", [])
    if not items:
        raise RuntimeError(f"Video {video_id} not found on this channel.")
    return items[0]


def set_privacy(video_id: str, privacy: str, publish_at: str | None = None) -> dict:
    """Change privacy, keeping the rest of `status` intact (update replaces the whole part)."""
    status = dict(get_status(video_id)["status"])
    for read_only in ("uploadStatus", "failureReason", "rejectionReason", "publishAt"):
        status.pop(read_only, None)
    status["privacyStatus"] = privacy
    if publish_at:  # scheduled publish requires private + publishAt
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    return _service().videos().update(part="status", body={"id": video_id, "status": status}).execute()
