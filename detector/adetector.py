import argparse
import json
from datetime import datetime
from pathlib import Path

import ollama


BASE_DIR = Path(__file__).resolve().parent.parent
MODEL = "gemma4:26b"


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


def get_transcription_path(station, recording_date, recording_name):
	filename = normalize_recording_filename(recording_name)

	return (
		BASE_DIR
		/ "asr"
		/ "text"
		/ station
		/ recording_date
		/ f"{filename}.txt"
	)


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
		"station",
		nargs="?",
		default="dubna-marusya",
		help="Radio station directory name",
	)
	parser.add_argument(
		"recording_time",
		nargs="?",
		default="18-14-00",
		help="Recording start time in HH-MM-SS format",
	)
	parser.add_argument(
		"recording_date",
		nargs="?",
		default="2026-08-18",
		help="Recording date folder in YYYY-MM-DD format",
	)
	args = parser.parse_args()

	try:
		transcription_path = get_transcription_path(
			args.station, args.recording_date, args.recording_time
		)
		if not transcription_path.is_file():
			raise FileNotFoundError(f"Transcription not found: {transcription_path}")

		transcription = transcription_path.read_text(encoding="utf-8")
		detection = detect_advertisements(transcription)
		detection_path = get_detection_path(
			args.station, args.recording_date, args.recording_time
		)
		save_detection(detection_path, detection)
		print(f"Advertisements found: {len(detection['advertisements'])}")
		print(f"Detection saved to: {detection_path}")
	except Exception as error:
		print(f"Error: {error}")
