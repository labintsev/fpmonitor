"""
Export the advertisements table from radio.db to a CSV file.
Usage:
    python export.py --output advertisements.csv
"""
import argparse
import csv
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "radio.db"


def export_advertisements_to_csv(output_path, db_path=DB_PATH):
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM advertisements").fetchall()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        if rows:
            writer.writerow(rows[0].keys())
            writer.writerows(rows)
        else:
            writer.writerow(
                [
                    "id",
                    "station",
                    "air_date",
                    "start_time",
                    "end_time",
                    "advertise",
                    "confidence",
                    "source_audio_file",
                    "audio_file",
                    "created_at",
                ]
            )

    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export the advertisements table to a CSV file.")
    parser.add_argument(
        "--output",
        default="advertisements.csv",
        help="Path to the output CSV file",
    )
    args = parser.parse_args()

    try:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = BASE_DIR / "data" / output_path

        row_count = export_advertisements_to_csv(output_path)
        print(f"Exported {row_count} rows to: {output_path}")
    except Exception as error:
        print(f"Error: {error}")
