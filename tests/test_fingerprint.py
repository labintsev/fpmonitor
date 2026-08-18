import sqlite3

from asr.fingerprint import fingerprint_audio_file, save_chunk_fingerprint


def test_fingerprint_audio_file_decodes_chromaprint(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "asr.fingerprint.acoustid.fingerprint_file",
        lambda path: (5.5, b"AQAA fingerprint"),
    )

    duration, fingerprint = fingerprint_audio_file(tmp_path / "chunk.wav")

    assert duration == 5.5
    assert fingerprint == "AQAA fingerprint"


def test_save_chunk_fingerprint_is_idempotent(tmp_path):
    db_path = tmp_path / "radio.db"
    audio_path = tmp_path / "recording.mp3"

    save_chunk_fingerprint(audio_path, 0, 6, 6, "first", db_path)
    save_chunk_fingerprint(audio_path, 0, 6, 6, "updated", db_path)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT audio_file, chunk_start, chunk_end, duration, fingerprint "
            "FROM audio_chunk_fingerprints"
        ).fetchall()

    assert rows == [(str(audio_path.resolve()), 0.0, 6.0, 6.0, "updated")]