import argparse
from datetime import datetime, timedelta
from pathlib import Path

import ollama


BASE_DIR = Path(__file__).resolve().parent.parent


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


def find_audio_path(radio_name, recording_date, recording_name):
    audio_root = BASE_DIR / "recorder" / "audio" / radio_name / recording_date
    filename = Path(recording_name).name
    if filename.lower().endswith(".mp3"):
        filename = filename[:-4]
    filename = f"{filename}.mp3"
    matches = list(audio_root.glob(filename))

    if not matches:
        raise FileNotFoundError(f"Audio file not found: {filename}")
    if len(matches) > 1:
        raise ValueError(f"More than one audio file found: {filename}")

    return matches[0]


def get_transcription_path(audio_file_path):
    audio_path = Path(audio_file_path).resolve()
    try:
        station, air_date, filename = audio_path.relative_to(
            BASE_DIR / "recorder" / "audio"
        ).parts
    except ValueError as error:
        raise ValueError(
            "Audio file must be located in recorder/audio/<station>/<date>/"
        ) from error

    return BASE_DIR / "asr" / "text" / station / air_date / f"{Path(filename).stem}.txt"


def save_transcription(audio_file_path, text):
    transcription_path = get_transcription_path(audio_file_path)
    transcription_path.parent.mkdir(parents=True, exist_ok=True)
    transcription_path.write_text(text, encoding="utf-8")
    return transcription_path


def transcribe_via_ollama(audio_file_path):
    print("📡 Connecting to local Ollama instance...")

    if not Path(audio_file_path).is_file():
        raise FileNotFoundError(f"Audio file not found at {audio_file_path}")

    # For multimodal audio endpoints, you pass the raw binary or path 
    # depending on the specific GGUF model configuration.
    response = ollama.chat(
        model="hf.co/foryoung365/Qwen3-ASR-1.7B-Q4_K_M-GGUF:Q4_K_M",
        messages=[
            {
                "role": "user",
                "content": "Преобразуй эту речь в текст с временными метками.",
                "images": [audio_file_path] 
                # Note: Ollama uses the 'images' array parameter to handle external binary assets 
            }
        ]
    )
    
    return response['message']['content']

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("recording_name", nargs="?", default="Avto_99.9", help="Audio recording base name, for example Avto_99.9")
    parser.add_argument("recording_time", nargs="?", default="1914", help="Recording start time in HHMM format, for example 1914")
    parser.add_argument("recording_date", nargs="?", default="2026-08-16", help="Audio recording date folder in YYYY-MM-DD format")
    parser.add_argument("radio_name", nargs="?", default="autoradio", help="Radio station name")
    parser.add_argument("--duration-minutes", type=int, default=7, help="Recording duration in minutes")
    args = parser.parse_args()

    try:
        recording_name = build_recording_name(
            args.recording_name, args.recording_time, args.duration_minutes
        )
        audio_path = find_audio_path(args.radio_name, args.recording_date, recording_name)
        text = transcribe_via_ollama(audio_path)
        output_path = save_transcription(audio_path, text)
        print(f"\n💾 Transcription saved to: {output_path}")
    except Exception as e:
        print(f"❌ Error: {e}")
