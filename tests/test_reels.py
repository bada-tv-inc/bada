import shutil
import subprocess
from array import array

import pytest

from bada.reels import make, signals
from bada.reels.make import Clip, Plan


def test_group_sentences():
    words = [(0, .3, " 이거"), (.3, .6, " 모르면"), (.6, .9, " 손해입니다."), (1, 1.2, " 진짜"), (2.5, 2.8, " 다음")]
    s = signals.group_sentences(words)
    assert [x.text for x in s] == ["이거 모르면 손해입니다.", "진짜", "다음"]


def test_scene_times_and_spikes():
    assert signals.parse_scene_times("n:0 pts:1 pts_time:1.2 x\nn:1 pts_time:3.5") == [1.2, 3.5]
    rate = 1000
    quiet = [100] * (2 * rate)
    loud = [20000] * (rate // 5)
    clipped = [32767] * 50
    pcm = array("h", quiet + loud + quiet + clipped + quiet)
    spikes = signals.find_spikes(pcm, rate)
    kinds = [(round(sp.time, 1), sp.kind) for sp in spikes]
    assert (2.0, "jump") in kinds
    assert any(k == "clip" for _, k in kinds)
    rows = signals.per_second(len(pcm) / rate, [0.5, 2.1, 2.4], pcm, rate, spikes)
    assert rows[2]["cuts"] == 2 and rows[2]["spikes"]


def test_validate_plan_and_word_mapping():
    plan = make.validate_plan({"clips": [
        {"start": 9, "end": 11, "layout": "full", "pop": True}, {"start": 0, "end": 0.2},
        {"start": 5, "end": 99, "layout": "canvas"}]}, duration=12, max_total=6)
    assert [(c.start, c.end, c.layout) for c in plan.clips] == [(9, 11, "full"), (5, 9, "canvas")]
    words = [(9.5, 9.8, " 결과"), (5.0, 5.4, " 왜"), (1.0, 1.2, " 버림")]
    assert make.words_on_reel(words, plan.clips) == [(0.5, 0.8, "결과"), (2.0, 2.4, "왜")]


def test_ass_has_words_headlines_cta():
    plan = Plan([Clip(0, 2, headline="결과 먼저"), Clip(4, 6)], cta_text="댓글에 {자료}")
    ass = make.build_ass([(0.1, 0.4, "안녕")], plan, 4.0, "Noto Sans CJK KR")
    assert ",Word,,0,0,0,," in ass and "안녕" in ass
    assert "결과 먼저" in ass
    assert "댓글에 (자료)" in ass and "0:00:01.00,0:00:04.00,CTA" in ass


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_signals_and_render_end_to_end(tmp_path):
    src = tmp_path / "raw.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=4",
                    "-f", "lavfi", "-i", "color=c=red:size=640x360:rate=25:duration=4",
                    "-f", "lavfi", "-i", "sine=duration=8",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-map", "2:a",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)], check=True)
    frames = signals.extract_hook_frames(src, tmp_path / "hook")
    assert len(frames) == 24 and frames[1].name == "00.125s.png"
    assert (tmp_path / "hook" / "sheet.jpg").exists()
    assert any(3.8 < c < 4.2 for c in signals.detect_cuts(src))

    plan = Plan([Clip(5, 7, "hook", "full", True, "결과"), Clip(0, 2, "proof", "canvas")], cta_text="댓글 '자료'")
    out = make.render(src, plan, [(5.2, 5.6, "결과"), (0.5, 0.9, "왜")], tmp_path / "reel", font="sans", log=lambda m: None)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout
    assert "1080,1920" in probe
