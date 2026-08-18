from detector.adetector import (
    BASE_DIR,
    detect_advertisements,
    get_detection_path,
    get_transcription_path,
)


def test_detector_paths_use_recording_filename():
    assert get_transcription_path(
        "dubna-marusya", "2026-08-18", "18-14-00.mp3"
    ) == (
        BASE_DIR
        / "asr"
        / "text"
        / "dubna-marusya"
        / "2026-08-18"
        / "18-14-00.txt"
    )
    assert get_detection_path(
        "dubna-marusya", "2026-08-18", "18-14-00.txt"
    ) == (
        BASE_DIR
        / "detector"
        / "text"
        / "dubna-marusya"
        / "2026-08-18"
        / "18-14-00.json"
    )


def test_detect_advertisements_requests_json_format(monkeypatch):
    captured = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {
            "message": {
                "content": '{"advertisements": []}',
            }
        }

    monkeypatch.setattr("detector.adetector.ollama.chat", fake_chat)

    assert detect_advertisements("00:00:00 - test") == {"advertisements": []}
    assert captured["format"] == "json"