"""End-to-end through ffmpeg with transcription and the LLM stubbed out."""
import json
import shutil
import subprocess

import pytest

from bada.youtube import llm, media, pipeline, transcribe
from bada.youtube.timeline import Segment

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture
def raw_video(tmp_path):
    # 3s tone, 3s silence, 3s tone, 3s tone (the "retake") = 12s
    path = tmp_path / "raw.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=12",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
         "-filter_complex", "[1:a]volume=enable='between(t,3,6)':volume=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path


def test_run_without_upload(raw_video, monkeypatch):
    segs = [Segment(0, 0.0, 3.0, "첫 문장"), Segment(1, 6.0, 9.0, "두번째 문장 실수"),
            Segment(2, 9.0, 12.0, "두번째 문장")]
    monkeypatch.setattr(transcribe, "transcribe", lambda *a, **k: segs)
    monkeypatch.setattr(llm, "decide_edits",
                        lambda model, s: llm.EditDecision([segs[1]], {1: "retake"}))
    monkeypatch.setattr(llm, "write_package", lambda model, s, lang: llm.Package(
        "제목", "설명", ["태그"], ["shorts"], [(0, "a")], "썸네일"))

    job = pipeline.run(raw_video, pipeline.Options(model="stub", upload=False), log=lambda m: None)

    work = pipeline.work_dir_for(raw_video)
    out = work / "final.mp4"
    assert job["final"] == str(out)
    # 12s - ~2.7s silence - 3s retake ~= 6.3s
    assert 5.5 < media.probe_duration(out) < 7.0
    srt = (work / "captions.srt").read_text()
    assert "첫 문장" in srt and "실수" not in srt
    package = json.loads((work / "package.json").read_text())
    assert package["description"].endswith("#shorts")
    assert "video_id" not in job
