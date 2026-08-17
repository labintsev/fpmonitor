from asr.asr_ollama import build_chunk_ranges, format_timestamp


def test_build_chunk_ranges_10s_with_1s_overlap():
    ranges = build_chunk_ranges(25, chunk_seconds=10, overlap_seconds=1)
    assert ranges == [(0, 10), (9, 19), (18, 25)]


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(61) == "00:01:01"
    assert format_timestamp(3661) == "01:01:01"
