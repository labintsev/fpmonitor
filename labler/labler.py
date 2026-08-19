"""
This script processes audio recordings from a specified radio station, 
extracts advertisement segments based on detection data, 
and saves them into a database. 
It uses the `av` library for audio processing and `sqlite3` for database management.
Usage:
    python labler.py --station dubna-avtoradio --recording_time 18-14-00 --recording_date 2026-08-18
"""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import av


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "radio.db"


def normalize_recording_time(recording_time):
	name = Path(recording_time).stem
	try:
		return datetime.strptime(name, "%H-%M-%S")
	except ValueError as error:
		raise ValueError(
			"Recording time must use HH-MM-SS format, for example 18-14-00"
		) from error


def get_source_audio_path(station, recording_date, recording_time):
	recording_start = normalize_recording_time(recording_time)
	return (
		BASE_DIR
		/ "recorder"
		/ "audio"
		/ station
		/ recording_date
		/ f"{recording_start:%H-%M-%S}.mp3"
	)


def get_detection_dir_path(station, recording_date):
	return BASE_DIR / "detector" / "text" / station / recording_date


def get_detection_path(station, recording_date, recording_time):
	recording_start = normalize_recording_time(recording_time)
	return get_detection_dir_path(station, recording_date) / f"{recording_start:%H-%M-%S}.json"


def find_detection_files(station, recording_date):
	"""Return every detection file (in order) inside detector/text/<station>/<date>/."""
	detection_dir = get_detection_dir_path(station, recording_date)
	if not detection_dir.is_dir():
		raise FileNotFoundError(f"Detection folder not found: {detection_dir}")

	detection_paths = sorted(detection_dir.glob("*.json"))
	if not detection_paths:
		raise FileNotFoundError(f"No detection files found in: {detection_dir}")

	return detection_paths


def get_label_audio_path(station, recording_date, ad_start):
	return (
		BASE_DIR
		/ "labler"
		/ "audio"
		/ station
		/ recording_date
		/ f"{ad_start:%H-%M-%S}.mp3"
	)


def load_advertisements(detection_path):
	if not detection_path.is_file():
		raise FileNotFoundError(f"Detection file not found: {detection_path}")

	data = json.loads(detection_path.read_text(encoding="utf-8"))
	advertisements = data.get("advertisements")
	if not isinstance(advertisements, list):
		raise ValueError(
			f"Invalid detection file, missing advertisements list: {detection_path}"
		)
	return advertisements


def get_ad_offsets_seconds(recording_start, ad):
	# Advertisement timestamps are absolute clock times, same as the recording start.
	ad_start = datetime.strptime(ad["start"], "%H:%M:%S")
	ad_end = datetime.strptime(ad["end"], "%H:%M:%S")

	start_seconds = (ad_start - recording_start).total_seconds() % 86400
	end_seconds = (ad_end - recording_start).total_seconds() % 86400

	if end_seconds <= start_seconds:
		raise ValueError(f"Advertisement end must be after start: {ad}")

	return start_seconds, end_seconds


def extract_audio_chunk(source_audio_path, start_seconds, end_seconds, output_path):
	output_path.parent.mkdir(parents=True, exist_ok=True)
	if output_path.exists():
		output_path.unlink()

	with av.open(str(source_audio_path), "r") as input_container:
		input_stream = next(
			(stream for stream in input_container.streams if stream.type == "audio"),
			None,
		)
		if input_stream is None:
			raise ValueError(f"No audio stream found in {source_audio_path}")

		sample_rate = input_stream.codec_context.sample_rate
		layout = input_stream.codec_context.layout

		with av.open(str(output_path), "w", format="mp3") as output_container:
			output_stream = output_container.add_stream("mp3", rate=sample_rate)
			output_stream.layout = layout
			resampler = av.AudioResampler(format="s16p", layout=layout, rate=sample_rate)
			packet_pts = 0

			for frame in input_container.decode(input_stream):
				if frame.pts is None:
					continue

				frame_time = float(frame.pts * input_stream.time_base)
				if frame_time < start_seconds:
					continue
				if frame_time >= end_seconds:
					break

				for resampled_frame in resampler.resample(frame):
					resampled_frame.pts = packet_pts
					packet_pts += resampled_frame.samples
					packet = output_stream.encode(resampled_frame)
					if packet is not None:
						output_container.mux(packet)

			for packet in output_stream.encode(None):
				output_container.mux(packet)

	if not output_path.is_file() or output_path.stat().st_size == 0:
		if output_path.exists():
			output_path.unlink()
		raise ValueError(
			f"Advertisement chunk is empty: {source_audio_path} ({start_seconds}-{end_seconds}s)"
		)


def init_db(db_path=DB_PATH):
	with sqlite3.connect(db_path) as connection:
		connection.execute(
			"""
			CREATE TABLE IF NOT EXISTS advertisements (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				station TEXT NOT NULL,
				air_date TEXT NOT NULL,
				start_time TEXT NOT NULL,
				end_time TEXT NOT NULL,
				advertise TEXT NOT NULL,
				confidence REAL,
				source_audio_file TEXT NOT NULL,
				audio_file TEXT NOT NULL,
				created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
				UNIQUE (station, air_date, start_time, end_time)
			)
			"""
		)


def save_advertisement(station, recording_date, ad, source_audio_path, audio_path, db_path=DB_PATH):
	init_db(db_path)
	with sqlite3.connect(db_path) as connection:
		connection.execute(
			"""
			INSERT INTO advertisements (
				station, air_date, start_time, end_time, advertise, confidence,
				source_audio_file, audio_file
			)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?)
			ON CONFLICT(station, air_date, start_time, end_time) DO UPDATE SET
				advertise = excluded.advertise,
				confidence = excluded.confidence,
				source_audio_file = excluded.source_audio_file,
				audio_file = excluded.audio_file
			""",
			(
				station,
				recording_date,
				ad["start"],
				ad["end"],
				ad["advertise"],
				ad.get("confidence"),
				str(source_audio_path),
				str(audio_path),
			),
		)


def label_advertisements(station, recording_date, recording_time):
	source_audio_path = get_source_audio_path(station, recording_date, recording_time)
	if not source_audio_path.is_file():
		raise FileNotFoundError(f"Source audio not found: {source_audio_path}")

	detection_path = get_detection_path(station, recording_date, recording_time)
	advertisements = load_advertisements(detection_path)
	recording_start = normalize_recording_time(recording_time)

	saved_paths = []
	for ad in advertisements:
		start_seconds, end_seconds = get_ad_offsets_seconds(recording_start, ad)
		ad_start_time = datetime.strptime(ad["start"], "%H:%M:%S")

		audio_path = get_label_audio_path(station, recording_date, ad_start_time)
		extract_audio_chunk(source_audio_path, start_seconds, end_seconds, audio_path)
		save_advertisement(station, recording_date, ad, source_audio_path, audio_path)
		saved_paths.append(audio_path)

	return saved_paths


if __name__ == "__main__":
	parser = argparse.ArgumentParser(
		description="Cut advertisement chunks out of a recording and store them in the database."
	)
	parser.add_argument(
		"--station",
		default="dubna-marusya",
		help="Radio station directory name",
	)
	parser.add_argument(
		"--recording_date",
		default="2026-08-18",
		help="Recording date folder in YYYY-MM-DD format",
	)
	parser.add_argument(
		"--recording_time",
		default=None,
		help=(
			"Recording start time in HH-MM-SS format; "
			"omit to process every detection file in the date folder"
		),
	)
	args = parser.parse_args()

	try:
		if args.recording_time:
			recording_times = [args.recording_time]
		else:
			recording_times = [
				path.stem for path in find_detection_files(args.station, args.recording_date)
			]
	except Exception as error:
		print(f"Error: {error}")
		recording_times = []

	for recording_time in recording_times:
		try:
			saved_paths = label_advertisements(args.station, args.recording_date, recording_time)
			print(f"Advertisements saved: {len(saved_paths)}")
			for path in saved_paths:
				print(f" - {path}")
		except Exception as error:
			print(f"Error processing {recording_time}: {error}")
