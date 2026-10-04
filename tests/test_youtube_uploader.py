from bada.youtube import uploader


class FakeService:
    def __init__(self):
        self.body = None

    def videos(self):
        return self

    def update(self, part, body):
        self.body = body
        return self

    def execute(self):
        return self.body


def _setup(monkeypatch):
    svc = FakeService()
    monkeypatch.setattr(uploader, "_service", lambda: svc)
    monkeypatch.setattr(uploader, "get_status", lambda vid: {"status": {
        "privacyStatus": "private", "uploadStatus": "processed", "license": "youtube",
        "embeddable": True, "selfDeclaredMadeForKids": False, "publishAt": "2030-01-01T00:00:00Z"}})
    return svc


def test_publish_keeps_other_status_fields(monkeypatch):
    svc = _setup(monkeypatch)
    uploader.set_privacy("abc", "public")
    status = svc.body["status"]
    assert status["privacyStatus"] == "public"
    assert status["license"] == "youtube" and status["embeddable"] is True
    assert "uploadStatus" not in status and "publishAt" not in status


def test_schedule_stays_private(monkeypatch):
    svc = _setup(monkeypatch)
    uploader.set_privacy("abc", "public", publish_at="2026-10-10T09:00:00+09:00")
    assert svc.body["status"]["privacyStatus"] == "private"
    assert svc.body["status"]["publishAt"] == "2026-10-10T09:00:00+09:00"
