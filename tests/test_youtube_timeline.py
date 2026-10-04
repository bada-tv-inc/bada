from bada.youtube import timeline as tl
from bada.youtube.llm import clean_tags, parse_json
from bada.youtube.media import build_select_filter, parse_silencedetect
from bada.youtube.timeline import Segment


def test_subtract_and_keep_intervals():
    assert tl.subtract_intervals([(0, 10)], [(2, 3), (5, 6)]) == [(0, 2), (3, 5), (6, 10)]
    keeps = tl.build_keep_intervals(
        10.0, silences=[(2.0, 4.0)], removed_segments=[Segment(1, 6.0, 7.0, "다시")], padding=0.5
    )
    assert keeps == [(0.0, 2.5), (3.5, 6.0), (7.0, 10.0)]
    assert tl.edited_duration(keeps) == 8.0


def test_tiny_keeps_dropped():
    keeps = tl.build_keep_intervals(10.0, [(0.0, 5.0), (5.2, 10.0)], [], padding=0.0)
    assert keeps == []


def test_remap():
    keeps = [(0.0, 2.0), (5.0, 8.0)]
    assert tl.remap_time(1.0, keeps) == 1.0
    assert tl.remap_time(3.0, keeps) is None
    assert tl.remap_time(6.0, keeps) == 3.0
    seg = tl.remap_segment(Segment(0, 1.5, 6.0, "hi"), keeps)
    assert (seg.start, seg.end) == (1.5, 3.0)
    assert tl.remap_segment(Segment(0, 2.5, 4.5, "gone"), keeps) is None


def test_srt():
    srt = tl.to_srt([Segment(0, 0.0, 1.5, "안녕"), Segment(1, 61.25, 3725.0, "bye")])
    assert "1\n00:00:00,000 --> 00:00:01,500\n안녕\n" in srt
    assert "2\n00:01:01,250 --> 01:02:05,000\nbye\n" in srt


def test_chapters_follow_youtube_rules():
    raw = [(3.0, "Intro"), (8.0, "too close"), (40.0, "Part 1"), (95.0, "Part 2"), (118.0, "too near end")]
    assert tl.validate_chapters(raw, 120.0) == [(0.0, "Intro"), (40.0, "Part 1"), (95.0, "Part 2")]
    assert tl.validate_chapters([(0, "a"), (30, "b")], 120.0) == []  # fewer than 3
    assert tl.chapters_block([(0.0, "a"), (75.0, "b"), (3700.0, "c")]) == "0:00 a\n1:15 b\n1:01:40 c"


def test_parse_silencedetect():
    stderr = (
        "[silencedetect @ 0x1] silence_start: -0.01\n"
        "[silencedetect @ 0x1] silence_end: 1.5 | silence_duration: 1.5\n"
        "[silencedetect @ 0x1] silence_start: 8.2\n"
    )
    assert parse_silencedetect(stderr, 10.0) == [(0.0, 1.5), (8.2, 10.0)]


def test_select_filter():
    f = build_select_filter([(0, 1), (2, 3.5)], audio=True)
    assert "between(t,0.000,1.000)+between(t,2.000,3.500)" in f
    assert "[a]" in f
    assert "[a]" not in build_select_filter([(0, 1)], audio=False)


def test_llm_helpers():
    assert parse_json('```json\n{"remove": [{"id": 3}]}\n```') == {"remove": [{"id": 3}]}
    tags = clean_tags(["a<b", "a<b", "two words", ""] + ["x" * 100] * 10)
    assert tags[:2] == ["ab", "two words"]
    assert sum(len(t) for t in tags) <= 500
