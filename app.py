from flask import Flask, render_template, request, jsonify
import sqlite3
from pathlib import Path

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "radio.db"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS radio_plays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            air_date TEXT NOT NULL,
            air_time TEXT NOT NULL,
            title TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_radio_plays_datetime
        ON radio_plays (air_date, air_time)
    """)

    conn.commit()
    conn.close()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/plays")
def get_plays():
    """
    GET /api/plays?date=2026-08-14&hour=14
    """

    selected_date = request.args.get("date")
    selected_hour = request.args.get("hour")

    if not selected_date or selected_hour is None:
        return jsonify({
            "success": False,
            "error": "Не указаны дата или час"
        }), 400

    try:
        hour = int(selected_hour)

        if hour < 0 or hour > 23:
            raise ValueError

    except ValueError:
        return jsonify({
            "success": False,
            "error": "Некорректное значение часа"
        }), 400

    # Например:
    # hour = 14
    #
    # ищем:
    # 14:00:00 <= air_time < 15:00:00

    start_time = f"{hour:02d}:00:00"

    if hour == 23:
        end_time = "24:00:00"
    else:
        end_time = f"{hour + 1:02d}:00:00"

    conn = get_db_connection()

    rows = conn.execute("""
        SELECT
            id,
            air_date,
            air_time,
            title
        FROM radio_plays
        WHERE air_date = ?
          AND air_time >= ?
          AND air_time < ?
        ORDER BY air_time ASC
    """, (
        selected_date,
        start_time,
        end_time
    )).fetchall()

    conn.close()

    plays = [
        {
            "id": row["id"],
            "date": row["air_date"],
            "time": row["air_time"],
            "title": row["title"]
        }
        for row in rows
    ]

    return jsonify({
        "success": True,
        "date": selected_date,
        "hour": hour,
        "count": len(plays),
        "plays": plays
    })


@app.route("/api/plays", methods=["POST"])
def add_play():
    """
    Добавление нового ролика.

    JSON:
    {
        "date": "2026-08-14",
        "time": "14:32:15",
        "title": "Coca-Cola Summer"
    }
    """

    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "error": "Нет данных"
        }), 400

    air_date = data.get("date")
    air_time = data.get("time")
    title = data.get("title")

    if not air_date or not air_time or not title:
        return jsonify({
            "success": False,
            "error": "Необходимо указать date, time и title"
        }), 400

    conn = get_db_connection()

    cursor = conn.execute("""
        INSERT INTO radio_plays (
            air_date,
            air_time,
            title
        )
        VALUES (?, ?, ?)
    """, (
        air_date,
        air_time,
        title
    ))

    conn.commit()

    new_id = cursor.lastrowid

    conn.close()

    return jsonify({
        "success": True,
        "id": new_id
    })


if __name__ == "__main__":
    init_db()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
    