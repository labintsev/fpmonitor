"""
ASR (Automatic Speech Recognition) module for processing audio recordings and generating timestamped transcriptions.
This script uses the `ollama` library to transcribe audio segments into text.
If recording_time is provided, it transcribes a single recording; 
otherwise, it processes all recordings for the specified date.
Usage:
    python asr/asr_ollama.py --station dubna-marusya --recording_date 2026-08-18 --recording_time 18-14-00
"""
import argparse
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import av
import ollama
from tqdm import tqdm

from fingerprint import fingerprint_and_save_chunk


BASE_DIR = Path(__file__).resolve().parent.parent
MODEL = "hf.co/foryoung365/Qwen3-ASR-1.7B-Q4_K_M-GGUF:Q4_K_M"
CHUNK_SECONDS = 6
OVERLAP_SECONDS = 1

# Bound each chat call so a stuck/runaway generation can't hang the whole run.
CHAT_TIMEOUT_SECONDS = 120
CHAT_MAX_TOKENS = 512
OLLAMA_CLIENT = ollama.Client(timeout=CHAT_TIMEOUT_SECONDS)

# Set in main() once the station is known.
LOGGER = None


def setup_logger(station):
	log_dir = BASE_DIR / "asr" / "text" / station / "logs"
	log_dir.mkdir(parents=True, exist_ok=True)

	logger = logging.getLogger(f"asr_ollama.{station}")
	logger.setLevel(logging.INFO)
	logger.propagate = False

	if logger.handlers:
		return logger

	handler = TimedRotatingFileHandler(
		log_dir / "asr_ollama.log",
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


def get_audio_dir_path(station, recording_date):
    return BASE_DIR / "recorder" / "audio" / station / recording_date


def get_audio_path(station, recording_date, recording_time):
    recording_start = get_recording_start_time(recording_time)
    return get_audio_dir_path(station, recording_date) / f"{recording_start:%H-%M-%S}.mp3"


def find_audio_files(station, recording_date):
    """Return every recording (in order) inside recorder/audio/<station>/<date>/."""
    audio_dir = get_audio_dir_path(station, recording_date)
    if not audio_dir.is_dir():
        raise FileNotFoundError(f"Recording folder not found: {audio_dir}")

    audio_paths = sorted(audio_dir.glob("*.mp3"))
    if not audio_paths:
        raise FileNotFoundError(f"No mp3 recordings found in: {audio_dir}")

    return audio_paths


def get_transcription_path(audio_file_path):
    audio_path = Path(audio_file_path).resolve()
    audio_root = (BASE_DIR / "recorder" / "audio").resolve()
    try:
        station, air_date, filename = audio_path.relative_to(audio_root).parts
    except ValueError as error:
        raise ValueError(
            "Audio file must be located in recorder/audio/<station>/<date>/"
        ) from error

    recording_time = get_recording_start_time(filename)

    return (
        BASE_DIR
        / "asr"
        / "text"
        / station
        / air_date
        / f"{recording_time:%H-%M-%S}.txt"
    )


def get_recording_start_time(audio_filename):
    try:
        return datetime.strptime(Path(audio_filename).stem, "%H-%M-%S")
    except ValueError as error:
        raise ValueError(
            "Audio file name must use HH-MM-SS.mp3 format, for example 18-14-00.mp3"
        ) from error


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

    if output_path.stat().st_size <= 44:
        output_path.unlink()
        raise ValueError(
            f"Audio chunk is empty: {audio_file_path} ({start_seconds}-{end_seconds}s)"
        )

    return output_path


def transcribe_via_ollama(audio_file_path, start_seconds=None, end_seconds=None):
    if not Path(audio_file_path).is_file():
        raise FileNotFoundError(f"Audio file not found at {audio_file_path}")

    prompt = "Преобразуй этот фрагмент речи в текст. Ответь только текстом, без комментариев."
    if start_seconds is not None and end_seconds is not None:
        prompt += (
            f" Временная привязка фрагмента: {format_timestamp(start_seconds)} - "
            f"{format_timestamp(end_seconds)}."
        )

    response = OLLAMA_CLIENT.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [str(audio_file_path)],
            }
        ],
        options={
            "num_predict": CHAT_MAX_TOKENS,
            "temperature": 0,
        },
        keep_alive="10m",
    )

    text = response["message"]["content"].strip()
    return text.replace('language Russian<asr_text>', ' ')


def transcribe_chunked_audio(
    audio_file_path,
    chunk_seconds=CHUNK_SECONDS,
    overlap_seconds=OVERLAP_SECONDS,
    db_path=None,
):
    total_duration = get_audio_duration(audio_file_path)
    segments = []

    chunk_ranges = build_chunk_ranges(
        total_duration, chunk_seconds=chunk_seconds, overlap_seconds=overlap_seconds
    )
    LOGGER.info(f"Processing {len(chunk_ranges)} chunks for {audio_file_path} ({total_duration:.2f}s total)")
    for start_seconds, end_seconds in tqdm(
        chunk_ranges,
        desc="ASR chunks",
        unit="chunk",
    ):
        chunk_path = split_audio_chunk(audio_file_path, start_seconds, end_seconds)
        processing_succeeded = False
        try:
            fingerprint_duration, fingerprint = fingerprint_and_save_chunk(
                chunk_path,
                audio_file_path,
                start_seconds,
                end_seconds,
                db_path=db_path or BASE_DIR / "radio.db",
            )
            text = transcribe_via_ollama(chunk_path, start_seconds, end_seconds)
            processing_succeeded = True
        except Exception as error:
            LOGGER.error(f"❌ Error processing {audio_file_path}: {error}")
            LOGGER.error(
                f"Could not process audio chunk {chunk_path} "
                f"({start_seconds}-{end_seconds}s). The chunk was kept for inspection."
            )
        finally:
            if chunk_path.exists() and processing_succeeded:
                chunk_path.unlink()

        segments.append(
            {
                "start": start_seconds,
                "end": end_seconds,
                "text": text,
                "fingerprint_duration": fingerprint_duration,
                "fingerprint": fingerprint,
            }
        )

    return segments


def save_transcription(audio_file_path, segments):
    transcription_path = get_transcription_path(audio_file_path)
    transcription_path.parent.mkdir(parents=True, exist_ok=True)
    recording_start_time = get_recording_start_time(audio_file_path)
    recording_start = (
        recording_start_time.hour * 3600
        + recording_start_time.minute * 60
        + recording_start_time.second
    )

    if isinstance(segments, str):
        text = segments
    else:
        text = "\n".join(
            f"{format_timestamp(recording_start + item['start'])} - {item['text']}"
            for item in segments
        )
    
    transcription_path.write_text(text, encoding="utf-8")
    return transcription_path


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
            "omit to transcribe every recording in the date folder"
        ),
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

    LOGGER = setup_logger(args.station)

    try:
        # Check if recording_time is provided; if so, transcribe that specific recording.
        # Otherwise, find all recordings for the specified date.
        if args.recording_time:
            audio_paths = [get_audio_path(args.station, args.recording_date, args.recording_time)]
        else:
            audio_paths = find_audio_files(args.station, args.recording_date)
    except Exception as error:
        LOGGER.error(f"❌ Error: {error}")
        audio_paths = []

    for audio_path in audio_paths:
        if not audio_path.is_file():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        segments = transcribe_chunked_audio(
            audio_path,
            chunk_seconds=args.chunk_seconds,
            overlap_seconds=args.overlap_seconds,
        )
        output_path = save_transcription(audio_path, segments)
        LOGGER.info(f"💾 Timestamped transcription saved to: {output_path}")
        LOGGER.info(f"✅ Processed {len(segments)} chunks with {args.chunk_seconds}s length and {args.overlap_seconds}s overlap")
