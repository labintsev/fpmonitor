import argparse
from datetime import datetime, timedelta
from pathlib import Path

import ollama
import yaml


BASE_DIR = Path(__file__).resolve().parent.parent
MODEL = "gemma4:e4b"


def build_recording_name(recording_name, recording_time, duration_minutes):
	try:
		start_time = datetime.strptime(recording_time, "%H%M")
	except ValueError as error:
		raise ValueError("Recording time must use HHMM format, for example 1914") from error

	end_time = start_time + timedelta(minutes=duration_minutes)
	base_name = Path(recording_name).name
	if base_name.lower().endswith((".mp3", ".txt")):
		base_name = base_name[:-4]
	return f"{base_name}_{start_time:%H%M}_{end_time:%H%M}"


def get_transcription_path(radio_name, recording_date, recording_name):
	filename = Path(recording_name).name
	if filename.lower().endswith(".mp3"):
		filename = filename[:-4]
	if filename.lower().endswith(".txt"):
		filename = filename[:-4]

	return (
		BASE_DIR
		/ "asr"
		/ "text"
		/ radio_name
		/ recording_date
		/ f"{filename}.txt"
	)


def get_detection_path(radio_name, recording_date, recording_name):
	filename = Path(recording_name).name
	if filename.lower().endswith(".mp3"):
		filename = filename[:-4]
	if filename.lower().endswith(".txt"):
		filename = filename[:-4]

	return (
		BASE_DIR
		/ "detector"
		/ "text"
		/ radio_name
		/ recording_date
		/ f"{filename}.yml"
	)


def build_prompt(transcription, duration_minutes):
	return f"""Проанализируй расшифровку радиоэфира и найди рекламные ролики.
Длительность аудиофайла: {duration_minutes} минут. Расшифровка может не содержать
временных меток, поэтому оцени временные границы роликов по положению текста.

Верни только корректный YAML без Markdown и без пояснений. Используй схему:
advertisements:
  - start: "00:00:00"
	end: "00:00:00"
	advertiser: "название бренда или организации"
	text: "краткое содержание рекламы"
	confidence: 0.0

Если рекламы нет, верни: advertisements: []

Расшифровка:
{transcription}"""


def detect_advertisements(transcription, duration_minutes):
	response = ollama.chat(
		model=MODEL,
		messages=[
			{
				"role": "user",
				"content": build_prompt(transcription, duration_minutes),
			}
		],
	)
	result = response["message"]["content"].strip()
	if result.startswith("```yaml"):
		result = result[7:]
	elif result.startswith("```"):
		result = result[3:]
	if result.endswith("```"):
		result = result[:-3]

	parsed_result = yaml.safe_load(result)
	if not isinstance(parsed_result, dict) or not isinstance(
		parsed_result.get("advertisements"), list
	):
		raise ValueError("Ollama response does not match the expected YAML schema")

	return parsed_result


def save_detection(detection_path, detection):
	detection_path.parent.mkdir(parents=True, exist_ok=True)
	detection_path.write_text(
		yaml.safe_dump(detection, allow_unicode=True, sort_keys=False), encoding="utf-8"
	)


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("recording_name", nargs="?", default="Avto_99.9", help="Recording base name, for example Avto_99.9")
	parser.add_argument("recording_time", nargs="?", default="1914", help="Recording start time in HHMM format, for example 1914")
	parser.add_argument("recording_date", nargs="?", default="2026-08-16", help="Recording date folder in YYYY-MM-DD format")
	parser.add_argument("radio_name", nargs="?", default="autoradio", help="Radio station name")
	parser.add_argument(
		"--duration-minutes",
		type=int,
		default=7,
		help="Recording duration used for estimated advertisement boundaries",
	)
	args = parser.parse_args()

	try:
		recording_name = build_recording_name(
			args.recording_name, args.recording_time, args.duration_minutes
		)
		transcription_path = get_transcription_path(
			args.radio_name, args.recording_date, recording_name
		)
		if not transcription_path.is_file():
			raise FileNotFoundError(f"Transcription not found: {transcription_path}")

		transcription = transcription_path.read_text(encoding="utf-8")
		detection = detect_advertisements(transcription, args.duration_minutes)
		detection_path = get_detection_path(
			args.radio_name, args.recording_date, recording_name
		)
		save_detection(detection_path, detection)
		print(f"Advertisements found: {len(detection['advertisements'])}")
		print(f"Detection saved to: {detection_path}")
	except Exception as error:
		print(f"Error: {error}")
