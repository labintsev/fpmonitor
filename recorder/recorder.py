import os
import time
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

STREAM_URL = "http://live.radio-city.fm/Avto_99.9"

OUTPUT_DIR = "recorder/audio/autoradio"
LOG_DIR = os.path.join(OUTPUT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "recorder.log")

# Записываем:
# XX:15:00 -> XX:25:00
# XX:45:00 -> XX:50:00

RECORDING_WINDOWS = [
    (14, 21),
    (44, 51),
]

READ_TIMEOUT = 30
TARGET_SAMPLE_RATE = 44100
TARGET_LAYOUT = "stereo"
TARGET_FORMAT = "fltp"

USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "Chrome/151.0 Safari/537.36"
)


def setup_logger():
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger("recorder")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    handler = TimedRotatingFileHandler(
        LOG_FILE,
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


logger = setup_logger()


# ============================================================
# HELPERS
# ============================================================

def get_current_window(now):
    """
    Returns:
        (start_datetime, end_datetime)
    for the current/next recording window.

    Windows:
        HH:15 -> HH:25
        HH:45 -> HH:50
    """

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
    """
    Returns the next recording window.
    """
    hour_base = now.replace(
        minute=0,
        second=0,
        microsecond=0,
    )

    candidates = []

    # Check windows in the current hour and the next hour.
    for hour_offset in (0, 1):
        window_hour = hour_base + timedelta(hours=hour_offset)

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
            Avto_99.9_1415_1425.mp3
    """

    date_dir = os.path.join(
        OUTPUT_DIR,
        start_time.strftime("%Y-%m-%d"),
    )

    os.makedirs(date_dir, exist_ok=True)

    filename = (
        f"Avto_99.9_"
        f"{start_time.strftime('%H%M')}_"
        f"{end_time.strftime('%H%M')}.mp3"
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

    filename = make_filename(start_time, end_time)

    logger.info("=" * 70)
    logger.info(f"Recording: {start_time:%Y-%m-%d %H:%M:%S}")
    logger.info(f"Until:     {end_time:%Y-%m-%d %H:%M:%S}")
    logger.info(f"File:      {filename}")
    logger.info("=" * 70)

    while True:

        now = datetime.now()

        if now >= end_time:
            logger.info("Recording window finished.")
            break

        try:

            logger.info("Connecting to stream...")

            bytes_written = 0
            started = time.monotonic()
            last_report_second = -1

            input_options = {
                "rw_timeout": str(READ_TIMEOUT * 1000000),
                "user_agent": USER_AGENT,
            }

            with av.open(
                STREAM_URL,
                mode="r",
                options=input_options,
            ) as input_container, av.open(
                filename,
                mode="w",
                format="mp3",
            ) as output_container:

                input_stream = next(
                    stream
                    for stream in input_container.streams
                    if stream.type == "audio"
                )

                logger.info(
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

                        elapsed = time.monotonic() - started
                        elapsed_second = int(elapsed)

                        if (
                            elapsed_second % 5 == 0
                            and elapsed_second != last_report_second
                        ):
                            last_report_second = elapsed_second
                            mb = bytes_written / 1024 / 1024
                            logger.info(
                                f"Encoded MP3: {mb:.2f} MB"
                            )

                for encoded_packet in output_stream.encode(None):
                    bytes_written += encoded_packet.size
                    output_container.mux(encoded_packet)

                if bytes_written > 0:
                    logger.info(
                        f"Saved {bytes_written / 1024 / 1024:.2f} MB"
                    )

                return

        except (
            AVError,
            OSError,
            StopIteration,
            ValueError,
        ) as e:

            logger.error(
                f"Stream error: {e}"
            )

            # Don't spin in a tight reconnect loop.
            remaining = (
                end_time - datetime.now()
            ).total_seconds()

            if remaining <= 0:
                break

            logger.info(
                "Retrying in 3 seconds..."
            )

            time.sleep(3)

        except Exception as e:
            logger.exception(
                "Unexpected recorder failure: %s",
                e,
            )

            remaining = (
                end_time - datetime.now()
            ).total_seconds()

            if remaining <= 0:
                break

            logger.info(
                "Retrying in 3 seconds..."
            )

            time.sleep(3)

        except KeyboardInterrupt:

            logger.info("Stopped by user.")
            return


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    logger.info("=" * 70)
    logger.info("Radio recorder")
    logger.info(STREAM_URL)
    logger.info("=" * 70)

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

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

        logger.info(
            f"Next recording: "
            f"{next_start:%Y-%m-%d %H:%M:%S}"
        )

        logger.info(
            f"Waiting {wait_seconds:.0f} seconds..."
        )

        try:
            time.sleep(
                max(1, wait_seconds)
            )

        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            break


if __name__ == "__main__":
    main()
