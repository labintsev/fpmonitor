import sqlite3

conn = sqlite3.connect("radio.db")


data = [
    ("2026-08-14", "14:01:12", "Coca-Cola Summer"),
    ("2026-08-14", "14:05:47", "McDonald's Big Mac"),
    ("2026-08-14", "14:11:03", "BMW X5"),
    ("2026-08-14", "14:17:25", "Pepsi Zero"),
    ("2026-08-14", "14:23:51", "Samsung Galaxy"),
    ("2026-08-14", "14:31:16", "Coca-Cola Summer"),
    ("2026-08-14", "14:38:42", "Nike Air Max"),
    ("2026-08-14", "15:02:11", "McDonald's Big Mac"),
    ("2026-08-14", "15:14:33", "BMW X5"),
    ("2026-08-14", "16:22:07", "Samsung Galaxy"),
]


conn.executemany("""
    INSERT INTO radio_plays (
        air_date,
        air_time,
        title
    )
    VALUES (?, ?, ?)
""", data)


conn.commit()
conn.close()

print("Test data inserted.")
