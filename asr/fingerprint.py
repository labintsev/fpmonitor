import sqlite3
from pathlib import Path

import acoustid


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "radio.db"


def init_fingerprint_db(db_path=DB_PATH):
	"""Create the chunk fingerprint table when it does not exist yet."""
	with sqlite3.connect(db_path) as connection:
		connection.execute(
			"""
			CREATE TABLE IF NOT EXISTS audio_chunk_fingerprints (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				audio_file TEXT NOT NULL,
				chunk_start REAL NOT NULL,
				chunk_end REAL NOT NULL,
				duration REAL NOT NULL,
				fingerprint TEXT NOT NULL,
				created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
				UNIQUE (audio_file, chunk_start, chunk_end)
			)
			"""
		)


def fingerprint_audio_file(audio_file_path):
	"""Return the Chromaprint duration and text fingerprint for an audio file."""
	try:
		duration, fingerprint = acoustid.fingerprint_file(str(audio_file_path))
	except acoustid.NoBackendError as error:
		raise RuntimeError(
			"Chromaprint backend is unavailable. Install fpcalc and add it to PATH "
			"or install libchromaprint for the active Python environment."
		) from error
	if isinstance(fingerprint, bytes):
		fingerprint = fingerprint.decode("ascii")
	return float(duration), fingerprint


def save_chunk_fingerprint(
	audio_file_path,
	chunk_start,
	chunk_end,
	duration,
	fingerprint,
	db_path=DB_PATH,
):
	"""Insert or update one chunk fingerprint in SQLite."""
	init_fingerprint_db(db_path)
	audio_file = str(Path(audio_file_path).resolve())
	with sqlite3.connect(db_path) as connection:
		connection.execute(
			"""
			INSERT INTO audio_chunk_fingerprints (
				audio_file, chunk_start, chunk_end, duration, fingerprint
			)
			VALUES (?, ?, ?, ?, ?)
			ON CONFLICT(audio_file, chunk_start, chunk_end) DO UPDATE SET
				duration = excluded.duration,
				fingerprint = excluded.fingerprint
			""",
			(audio_file, float(chunk_start), float(chunk_end), float(duration), fingerprint),
		)


def fingerprint_and_save_chunk(
	chunk_path,
	audio_file_path,
	chunk_start,
	chunk_end,
	db_path=DB_PATH,
):
	duration, fingerprint = fingerprint_audio_file(chunk_path)
	save_chunk_fingerprint(
		audio_file_path,
		chunk_start,
		chunk_end,
		duration,
		fingerprint,
		db_path=db_path,
	)
	return duration, fingerprint
