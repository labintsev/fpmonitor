import argparse
import os
import time
from pathlib import Path
import logging
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler

import av

try:
    AVError = av.AVError
except AttributeError:
    try:
        AVError = av.error.FFmpegError
    except AttributeError:
        AVError = Exception


# ============================================================
# CONFIG
# ============================================================
BASE_DIR = Path(__file__).parent.resolve()
AUDIO_STREAM_TYPE = "auto"
# Will be set in main()
STREAM_URL = None
AUDIO_DIR = None  
LOGGER = None

# Записываем:
# XX:15:00 -> XX:25:00
# XX:45:00 -> XX:50:00

RECORDING_WINDOWS = [
    (14, 21),
    (44, 51),
]

# Only record between 06:00 and 23:59; the last window in hour 23 ends at 23:51.
ACTIVE_START_HOUR = 6
ACTIVE_END_HOUR = 23

READ_TIMEOUT = 30
TARGET_SAMPLE_RATE = 16000
TARGET_LAYOUT = "stereo"
TARGET_FORMAT = "fltp"

USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "Chrome/151.0 Safari/537.36"
)


def setup_logger(log_dir, log_file):
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("recorder")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    handler = TimedRotatingFileHandler(
        log_file,
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

    return logger


# ============================================================
# HELPERS
# ============================================================

def is_active_hour(dt):
    """Whether dt falls within the daily 06:00-23:59 recording period."""
    return ACTIVE_START_HOUR <= dt.hour <= ACTIVE_END_HOUR


def get_current_window(now):
    """
    Returns:
        (start_datetime, end_datetime)
    for the current/next recording window.

    Windows:
        HH:15 -> HH:25
        HH:45 -> HH:50
    """

    if not is_active_hour(now):
        return None

    base = now.replace(second=0, microsecond=0)

    for start_minute, end_minute in RECORDING_WINDOWS:

        start = base.replace(
            minute=start_minute,
            second=0,
            microsecond=0,
        )

        end = base.replace(
            minute=end_minute,
            second=0,
            microsecond=0,
        )

        if end <= start:
            end += timedelta(hours=1)

        if start <= now < end:
            return start, end

    return None


def get_next_window(now):
    hour_base = now.replace(
        minute=0,
        second=0,
        microsecond=0,
    )

    candidates = []

    # Look up to two days ahead so we can skip past inactive hours (00:00-05:59).
    for hour_offset in range(0, 48):
        window_hour = hour_base + timedelta(hours=hour_offset)

        if not is_active_hour(window_hour):
            continue

        for start_minute, end_minute in RECORDING_WINDOWS:

            start = window_hour.replace(
                minute=start_minute,
            )

            end = window_hour.replace(
                minute=end_minute,
            )

            if end <= start:
                end += timedelta(hours=1)

            if start > now:
                candidates.append((start, end))

    if candidates:
        return min(candidates, key=lambda x: x[0])

    raise ValueError("RECORDING_WINDOWS is empty")


def make_filename(start_time, end_time):
    """
    Example:

    recorder/
      audio/
        autoradio/
          2026-08-14/
            14-15-03.mp3
    """

    date_dir = os.path.join(
        AUDIO_DIR,
        start_time.strftime("%Y-%m-%d"),
    )

    os.makedirs(date_dir, exist_ok=True)

    filename = (
        f"{start_time.strftime('%H-%M-%S')}.mp3"
    )

    return os.path.join(date_dir, filename)


# ============================================================
# RECORD
# ============================================================

def record_stream(start_time, end_time):
    """
    Connect to AAC radio stream, decode audio frames,
    encode to MP3 and save until end_time.
    """

    LOGGER.info("=" * 70)
    LOGGER.info(f"Recording: {start_time:%Y-%m-%d %H:%M:%S}")
    LOGGER.info(f"Until:     {end_time:%Y-%m-%d %H:%M:%S}")
    LOGGER.info("=" * 70)

    while True:

        now = datetime.now()

        if now >= end_time:
            LOGGER.info("Recording window finished.")
            break

        try:

            LOGGER.info("Connecting to stream...")

            bytes_written = 0
            started = time.monotonic()
            last_report_second = -1

            input_options = {
                "rw_timeout": str(READ_TIMEOUT * 1000000),
                "user_agent": USER_AGENT,
            }

            open_kwargs = {
                "mode": "r",
                "options": input_options,
            }
            if AUDIO_STREAM_TYPE != "auto":
                open_kwargs["format"] = AUDIO_STREAM_TYPE

            input_container = av.open(STREAM_URL, **open_kwargs)

            recording_start = datetime.now()
            filename = make_filename(recording_start, end_time)
            LOGGER.info(f"Recording started: {recording_start:%Y-%m-%d %H:%M:%S}")
            LOGGER.info(f"File:              {filename}")

            with input_container, av.open(
                filename,
                mode="w",
                format="mp3",
            ) as output_container:

                input_stream = next(
                    stream
                    for stream in input_container.streams
                    if stream.type == "audio"
                )

                LOGGER.info(
                    "Input codec: %s | rate: %s Hz | channels: %s",
                    input_stream.codec_context.name,
                    input_stream.codec_context.sample_rate,
                    input_stream.codec_context.channels,
                )

                output_stream = output_container.add_stream(
                    "libmp3lame",
                    rate=TARGET_SAMPLE_RATE,
                )
                output_stream.layout = TARGET_LAYOUT

                resampler = av.audio.resampler.AudioResampler(
                    format=TARGET_FORMAT,
                    layout=TARGET_LAYOUT,
                    rate=TARGET_SAMPLE_RATE,
                )

                stopped_by_user = False
                try:
                    for packet in input_container.demux(input_stream):

                        now = datetime.now()

                        # Stop exactly at the end of the window.
                        if now >= end_time:
                            break

                        for frame in packet.decode():

                            now = datetime.now()

                            if now >= end_time:
                                break

                            resampled_frames = resampler.resample(frame)

                            if not isinstance(resampled_frames, list):
                                resampled_frames = [resampled_frames]

                            for resampled_frame in resampled_frames:

                                if resampled_frame is None:
                                    continue

                                encoded_packets = output_stream.encode(
                                    resampled_frame
                                )

                                for encoded_packet in encoded_packets:
                                    bytes_written += encoded_packet.size
                                    output_container.mux(encoded_packet)

                    mb = bytes_written / 1024 / 1024
                    LOGGER.info(f"Encoded MP3: {mb:.2f} MB")
                    
                except KeyboardInterrupt:
                    stopped_by_user = True
                    LOGGER.info("Stopping recording and saving the file...")

                for encoded_packet in output_stream.encode(None):
                    bytes_written += encoded_packet.size
                    output_container.mux(encoded_packet)

                if bytes_written > 0:
                    LOGGER.info(
                        f"Saved {bytes_written / 1024 / 1024:.2f} MB"
                    )

                if stopped_by_user:
                    return

                return

        except (
            AVError,
            OSError,
            StopIteration,
            ValueError,
        ) as e:

            LOGGER.error(
                f"Stream error: {e}"
            )

            # Don't spin in a tight reconnect loop.
            remaining = (
                end_time - datetime.now()
            ).total_seconds()

            if remaining <= 0:
                break

            LOGGER.info(
                "Retrying in 3 seconds..."
            )

            time.sleep(3)

        except Exception as e:
            LOGGER.exception(
                "Unexpected recorder failure: %s",
                e,
            )

            remaining = (
                end_time - datetime.now()
            ).total_seconds()

            if remaining <= 0:
                break

            LOGGER.info(
                "Retrying in 3 seconds..."
            )

            time.sleep(3)

        except KeyboardInterrupt:

            LOGGER.info("Stopped by user.")
            return


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    global STREAM_URL, AUDIO_STREAM_TYPE, AUDIO_DIR, LOGGER

    parser = argparse.ArgumentParser(description="Record the radio stream on schedule")
    parser.add_argument(
        "--stream-url",
        default="https://stream.autoradio.ru/autoradio",
        help="Audio stream URL",
    )
    parser.add_argument(
        "--stream-type",
        choices=("auto", "mp3", "aac"),
        default="auto",
        help="Input stream type; auto lets FFmpeg detect it",
    )
    parser.add_argument(
        "--output-dir",
        default="autoradio",
        help="Directory where dated recordings and logs are stored",
    )
    args = parser.parse_args()

    STREAM_URL = args.stream_url
    AUDIO_STREAM_TYPE = args.stream_type
    AUDIO_DIR = Path(BASE_DIR / "audio" / args.output_dir)
    log_dir = AUDIO_DIR / "logs"
    log_file = log_dir / "recorder.log"
    LOGGER = setup_logger(log_dir, log_file)

    LOGGER.info("=" * 70)
    LOGGER.info("Radio recorder")
    LOGGER.info(STREAM_URL)
    LOGGER.info(f"Stream type: {AUDIO_STREAM_TYPE}")
    LOGGER.info("=" * 70)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    while True:

        now = datetime.now()

        current = get_current_window(now)

        if current:

            start_time, end_time = current

            # If the program was started in the middle
            # of a recording window, start immediately.
            record_stream(
                start_time,
                end_time,
            )

            continue

        next_start, next_end = get_next_window(now)

        wait_seconds = max(
            0,
            (next_start - now).total_seconds(),
        )

        LOGGER.info(
            f"Next recording: "
            f"{next_start:%Y-%m-%d %H:%M:%S}"
        )

        LOGGER.info(
            f"Waiting {wait_seconds:.0f} seconds..."
        )

        try:
            time.sleep(
                max(1, wait_seconds)
            )

        except KeyboardInterrupt:
            LOGGER.info("Stopped by user.")
            break


if __name__ == "__main__":
    main()
