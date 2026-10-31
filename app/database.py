"""Слой работы с базой данных (SQLite).

Хранит пользователей, инвентарь (лыжи) и бронирования.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = "skiprokat.db"


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Создаёт таблицы и наполняет справочные данные при первом запуске."""
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'user'  -- user | employee | admin
            );

            CREATE TABLE IF NOT EXISTS equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,               -- модель/название
                type TEXT NOT NULL DEFAULT 'ski', -- ski | snowboard | boots ...
                size TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ok' -- ok | maintenance
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                equipment_id INTEGER REFERENCES equipment(id),
                date TEXT NOT NULL,               -- YYYY-MM-DD
                start_time TEXT NOT NULL,         -- HH:MM
                duration_hours INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active', -- active|done|cancelled
                created_at TEXT NOT NULL,
                UNIQUE(equipment_id, date, start_time)
            );
            """
        )

        # Инвентарь по умолчанию
        if db.execute("SELECT COUNT(*) c FROM equipment").fetchone()["c"] == 0:
            db.executemany(
                "INSERT INTO equipment (name, type, size) VALUES (?, ?, ?)",
                [
                    ("Лыжи беговые Fischer Expert", "ski", "180"),
                    ("Лыжи беговые Rossignol Comp", "ski", "190"),
                    ("Лыжи горные Salomon Q9", "ski", "170"),
                    ("Лыжи горные Atomic Redster", "ski", "175"),
                    ("Сноуборд Burton Custom", "snowboard", "M"),
                    ("Ботинки лыжные Nordica", "boots", "42"),
                ],
            )

        # Служебные аккаунты: admin/admin123, employee/emp123
        from app.auth import hash_password

        exists = db.execute("SELECT COUNT(*) c FROM users WHERE role='admin'").fetchone()["c"]
        if exists == 0:
            db.executemany(
                "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
                [
                    ("admin", hash_password("admin123"), "Администратор", "admin"),
                    ("employee", hash_password("emp123"), "Сотрудник проката", "employee"),
                ],
            )


if __name__ == "__main__":
    init_db()
    print("База данных инициализирована:", DB_PATH)
