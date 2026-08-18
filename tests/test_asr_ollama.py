from asr.asr_ollama import (
    BASE_DIR,
    build_chunk_ranges,
    format_timestamp,
    get_transcription_path,
    save_transcription,
)


def test_build_chunk_ranges_10s_with_1s_overlap():
    ranges = build_chunk_ranges(25, chunk_seconds=10, overlap_seconds=1)
    assert ranges == [(0, 10), (9, 19), (18, 25)]


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(61) == "00:01:01"
    assert format_timestamp(3661) == "01:01:01"


def test_get_transcription_path_uses_exact_recording_start_time():
    audio_path = BASE_DIR / "recorder" / "audio" / "dubna-marusya" / "2026-08-18" / "18-14-00.mp3"

    assert get_transcription_path(audio_path) == (
        BASE_DIR / "asr" / "text" / "dubna-marusya" / "2026-08-18" / "18-14-00.txt"
    )


def test_save_transcription_uses_recording_start_time(tmp_path, monkeypatch):
    import asr.asr_ollama as asr_ollama

    monkeypatch.setattr(asr_ollama, "BASE_DIR", tmp_path)
    audio_path = tmp_path / "recorder" / "audio" / "dubna-marusya" / "2026-08-18" / "18-14-00.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"")

    transcription_path = save_transcription(
        audio_path,
        [
            {"start": 0, "text": "Маруся FM"},
            {"start": 5, "text": "language English<asr_text>Hello"},
        ],
    )

    assert transcription_path.read_text(encoding="utf-8") == (
        "18:14:00 - Маруся FM\n"
        "18:14:05 - language English<asr_text>Hello"
    )
