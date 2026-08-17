import argparse
from datetime import datetime, timedelta
from pathlib import Path

import av
import ollama


BASE_DIR = Path(__file__).resolve().parent.parent
MODEL = "hf.co/foryoung365/Qwen3-ASR-1.7B-Q4_K_M-GGUF:Q4_K_M"
CHUNK_SECONDS = 6
OVERLAP_SECONDS = 1



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


def format_timestamp(total_seconds):
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_filename_timestamp(total_seconds):
    return format_timestamp(total_seconds).replace(":", "-")


def build_chunk_ranges(total_seconds, chunk_seconds=CHUNK_SECONDS, overlap_seconds=OVERLAP_SECONDS):
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be greater than zero")
    if overlap_seconds < 0 or overlap_seconds >= chunk_seconds:
        raise ValueError("overlap_seconds must be between 0 and chunk_seconds")
    if total_seconds <= 0:
        return [(0, 0)]

    ranges = []
    start = 0
    while start < total_seconds:
        end = min(start + chunk_seconds, total_seconds)
        ranges.append((start, end))
        if end >= total_seconds:
            break
        start += chunk_seconds - overlap_seconds
    return ranges


def get_audio_duration(audio_file_path):
    """Get the duration of an audio file in seconds using av."""
    with av.open(audio_file_path) as container:
        audio_stream = next(
            (stream for stream in container.streams if stream.type == "audio"),
            None,
        )
        if audio_stream is None:
            raise ValueError(f"No audio stream found in {audio_file_path}")

        duration = float(audio_stream.duration) * float(audio_stream.time_base)
        if duration <= 0:
            raise ValueError(f"Could not determine duration for audio file: {audio_file_path}")
        return duration


def split_audio_chunk(audio_file_path, start_seconds, end_seconds):
    chunk_dir = Path(audio_file_path).resolve().parent / ".asr_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    start_tag = format_filename_timestamp(start_seconds)
    end_tag = format_filename_timestamp(end_seconds)
    output_path = chunk_dir / f"{Path(audio_file_path).stem}_{start_tag}_{end_tag}.wav"

    if output_path.exists():
        output_path.unlink()

    with av.open(str(audio_file_path), "r") as input_container:
        input_stream = next(
            (stream for stream in input_container.streams if stream.type == "audio"),
            None,
        )
        if input_stream is None:
            raise ValueError(f"No audio stream found in {audio_file_path}")

        with av.open(str(output_path), "w", format="wav") as output_container:
            output_stream = output_container.add_stream("pcm_s16le", 16000)
            output_stream.layout = "mono"
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
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

    return output_path


def transcribe_via_ollama(audio_file_path, start_seconds=None, end_seconds=None):
    print(f"📡 Connecting to local Ollama instance for segment {start_seconds}-{end_seconds}...")

    if not Path(audio_file_path).is_file():
        raise FileNotFoundError(f"Audio file not found at {audio_file_path}")

    prompt = "Преобразуй этот фрагмент речи в текст. Ответь только текстом, без комментариев."
    if start_seconds is not None and end_seconds is not None:
        prompt += (
            f" Временная привязка фрагмента: {format_timestamp(start_seconds)} - "
            f"{format_timestamp(end_seconds)}."
        )

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [str(audio_file_path)],
            }
        ],
    )

    text = response["message"]["content"].strip()
    return text.replace('language Russian<asr_text>', ' ')


def transcribe_chunked_audio(audio_file_path, chunk_seconds=CHUNK_SECONDS, overlap_seconds=OVERLAP_SECONDS):
    total_duration = get_audio_duration(audio_file_path)
    segments = []

    for start_seconds, end_seconds in build_chunk_ranges(
        total_duration, chunk_seconds=chunk_seconds, overlap_seconds=overlap_seconds
    ):
        chunk_path = split_audio_chunk(audio_file_path, start_seconds, end_seconds)
        try:
            text = transcribe_via_ollama(chunk_path, start_seconds, end_seconds)
        finally:
            if chunk_path.exists():
                chunk_path.unlink()

        segments.append(
            {
                "start": start_seconds,
                "end": end_seconds,
                "text": text,
            }
        )

    return segments


def save_transcription(audio_file_path, segments):
    transcription_path = get_transcription_path(audio_file_path)
    transcription_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(segments, str):
        text = segments
    else:
        text = "\n".join(
            f"{format_timestamp(item['start'])} - {item['text']}"
            for item in segments
        )
    
    transcription_path.write_text(text, encoding="utf-8")
    return transcription_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "recording_name",
        nargs="?",
        default="Avto_99.9",
        help="Audio recording base name, for example Avto_99.9",
    )
    parser.add_argument(
        "recording_time",
        nargs="?",
        default="1914",
        help="Recording start time in HHMM format, for example 1914",
    )
    parser.add_argument(
        "recording_date",
        nargs="?",
        default="2026-08-16",
        help="Audio recording date folder in YYYY-MM-DD format",
    )
    parser.add_argument(
        "radio_name",
        nargs="?",
        default="autoradio",
        help="Radio station name",
    )
    parser.add_argument(
        "--duration-minutes",
        type=int,
        default=7,
        help="Recording duration in minutes",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=CHUNK_SECONDS,
        help="Chunk length in seconds for ASR segmentation",
    )
    parser.add_argument(
        "--overlap-seconds",
        type=int,
        default=OVERLAP_SECONDS,
        help="Audio overlap between chunks in seconds",
    )
    args = parser.parse_args()

    try:
        recording_name = build_recording_name(
            args.recording_name, args.recording_time, args.duration_minutes
        )
        audio_path = find_audio_path(args.radio_name, args.recording_date, recording_name)
        segments = transcribe_chunked_audio(
            audio_path,
            chunk_seconds=args.chunk_seconds,
            overlap_seconds=args.overlap_seconds,
        )
        output_path = save_transcription(audio_path, segments)
        print(f"\n💾 Timestamped transcription saved to: {output_path}")
        print(f"✅ Processed {len(segments)} chunks with {args.chunk_seconds}s length and {args.overlap_seconds}s overlap")
    except Exception as error:
        print(f"❌ Error: {error}")
