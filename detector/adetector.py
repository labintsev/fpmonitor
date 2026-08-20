"""
This script detects advertisements in radio transcriptions using the Ollama API.
It processes transcriptions from a specified radio station and date,
and saves the detected advertisement segments into a JSON file.
Usage:
	python detector/adetector.py --station dubna-avtoradio --recording_date 2026-08-18 --recording_time 18-14-00"""
import argparse
import json
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import ollama


BASE_DIR = Path(__file__).resolve().parent.parent
MODEL = "gemma4:26b"

# Set in main() once the station is known.
LOGGER = None


def setup_logger(station):
	log_dir = BASE_DIR / "detector" / "text" / station / "logs"
	log_dir.mkdir(parents=True, exist_ok=True)

	logger = logging.getLogger(f"adetector.{station}")
	logger.setLevel(logging.INFO)
	logger.propagate = False

	if logger.handlers:
		return logger

	handler = TimedRotatingFileHandler(
		log_dir / "adetector.log",
		when="midnight",
		interval=1,
		backupCount=30,
		encoding="utf-8",
	)
	handler.suffix = "%Y-%m-%d"

	formatter = logging.Formatter(
		"%(asctime)s | %(levelname)s | %(message)s",
		"%Y-%m-%d %H:%M:%S",
	)
	handler.setFormatter(formatter)
	logger.addHandler(handler)

	console_handler = logging.StreamHandler()
	console_handler.setFormatter(formatter)
	logger.addHandler(console_handler)

	return logger


def normalize_recording_filename(recording_name):
	filename = Path(recording_name).name
	if filename.lower().endswith((".mp3", ".txt", ".json")):
		filename = Path(filename).stem

	try:
		datetime.strptime(filename, "%H-%M-%S")
	except ValueError as error:
		raise ValueError(
			"Recording name must use HH-MM-SS format, for example 18-14-00"
		) from error

	return filename


def get_transcription_dir_path(station, recording_date):
	return BASE_DIR / "asr" / "text" / station / recording_date


def get_transcription_path(station, recording_date, recording_name):
	filename = normalize_recording_filename(recording_name)

	return get_transcription_dir_path(station, recording_date) / f"{filename}.txt"


def find_transcription_files(station, recording_date):
	"""Return every transcription (in order) inside asr/text/<station>/<date>/."""
	transcription_dir = get_transcription_dir_path(station, recording_date)
	if not transcription_dir.is_dir():
		raise FileNotFoundError(f"Transcription folder not found: {transcription_dir}")

	transcription_paths = sorted(transcription_dir.glob("*.txt"))
	if not transcription_paths:
		raise FileNotFoundError(f"No transcriptions found in: {transcription_dir}")

	return transcription_paths


def get_detection_path(station, recording_date, recording_name):
	filename = normalize_recording_filename(recording_name)

	return (
		BASE_DIR
		/ "detector"
		/ "text"
		/ station
		/ recording_date
		/ f"{filename}.json"
	)


def build_prompt(transcription):
	return f"""Проанализируй расшифровку радиоэфира и найди рекламные ролики.
Обращай внимание на тему рекламы, в одном чанке может быть конец одной рекламы и начало другой.
Расшифровка содержит временные метки, оцени временные границы роликов.
Продолжительность одного ролика обычно составляет от 15 до 40 секунд.
Верни только корректный JSON без Markdown и без пояснений. Используй схему:
{{
	"advertisements": [
		{{
			"start": "00:00:00",
			"end": "00:00:00",
			"advertise": "название бренда или организации и краткое содержание рекламы",
			"confidence": 0.0
		}}
	]
}}

Если рекламы нет, верни: {{"advertisements": []}}

Расшифровка:
{transcription}"""


def detect_advertisements(transcription, duration_minutes=7):
	response = ollama.chat(
		model=MODEL,
		format="json",
		messages=[
			{
				"role": "user",
				"content": build_prompt(transcription),
			}
		],
	)
	result = response["message"]["content"].strip()
	if result.startswith("```json"):
		result = result[7:]
	elif result.startswith("```"):
		result = result[3:]
	if result.endswith("```"):
		result = result[:-3]

	parsed_result = json.loads(result.strip())
	if not isinstance(parsed_result, dict) or not isinstance(
		parsed_result.get("advertisements"), list
	):
		raise ValueError("Ollama response does not match the expected JSON schema")

	return parsed_result


def save_detection(detection_path, detection):
	detection_path.parent.mkdir(parents=True, exist_ok=True)
	detection_path.write_text(
		json.dumps(detection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
	)


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
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
			"omit to process every transcription in the date folder"
		),
	)
	args = parser.parse_args()

	LOGGER = setup_logger(args.station)

	try:
		if args.recording_time:
			transcription_paths = [
				get_transcription_path(args.station, args.recording_date, args.recording_time)
			]
		else:
			transcription_paths = find_transcription_files(args.station, args.recording_date)
	except Exception as error:
		LOGGER.error(f"Error: {error}")
		transcription_paths = []

	for transcription_path in transcription_paths:
		try:
			if not transcription_path.is_file():
				raise FileNotFoundError(f"Transcription not found: {transcription_path}")

			transcription = transcription_path.read_text(encoding="utf-8")
			detection = detect_advertisements(transcription)
			detection_path = get_detection_path(
				args.station, args.recording_date, transcription_path.stem
			)
			save_detection(detection_path, detection)
			LOGGER.info(f"Advertisements found: {len(detection['advertisements'])}")
			LOGGER.info(f"Detection saved to: {detection_path}")
		except Exception as error:
			LOGGER.error(f"Error processing {transcription_path}: {error}")
