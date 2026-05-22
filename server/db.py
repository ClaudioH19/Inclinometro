from __future__ import annotations

import csv
import os
import sqlite3
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("SQLITE_PATH", DATA_DIR / "clinostat.db"))


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def initialize_db() -> None:
    with connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS motion_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                batch_id INTEGER NOT NULL,
                sample_index INTEGER NOT NULL,
                sample_time_us INTEGER NOT NULL,
                accel_x_raw INTEGER NOT NULL,
                accel_y_raw INTEGER NOT NULL,
                accel_z_raw INTEGER NOT NULL,
                gyro_x_raw INTEGER NOT NULL,
                gyro_y_raw INTEGER NOT NULL,
                gyro_z_raw INTEGER NOT NULL,
                received_at TEXT NOT NULL,
                UNIQUE(session_id, batch_id, sample_index)
            );

            CREATE INDEX IF NOT EXISTS idx_motion_records_session
            ON motion_records(session_id, batch_id, sample_index);

            CREATE INDEX IF NOT EXISTS idx_motion_records_received
            ON motion_records(received_at);
            """
        )


def insert_batch(session_id: str, batch_id: int, samples: list[list[int]]) -> int:
    received_at = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            session_id,
            batch_id,
            i,
            sample[0],
            sample[1],
            sample[2],
            sample[3],
            sample[4],
            sample[5],
            sample[6],
            received_at,
        )
        for i, sample in enumerate(samples)
    ]
    with connect_db() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO motion_records (
                session_id,
                batch_id,
                sample_index,
                sample_time_us,
                accel_x_raw,
                accel_y_raw,
                accel_z_raw,
                gyro_x_raw,
                gyro_y_raw,
                gyro_z_raw,
                received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    return len(rows)


def filters_where(filters: dict) -> tuple[str, list]:
    clauses = []
    params = []
    if filters.get("session_id"):
        clauses.append("session_id = ?")
        params.append(filters["session_id"])
    if filters.get("received_after"):
        clauses.append("received_at >= ?")
        params.append(filters["received_after"])
    if filters.get("received_before"):
        clauses.append("received_at <= ?")
        params.append(filters["received_before"])
    return ("WHERE " + " AND ".join(clauses), params) if clauses else ("", [])


def list_sessions() -> list[dict]:
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                session_id,
                COUNT(*) AS sample_count,
                MIN(sample_time_us) AS first_sample_time_us,
                MAX(sample_time_us) AS last_sample_time_us,
                MIN(received_at) AS first_received_at,
                MAX(received_at) AS last_received_at,
                COUNT(DISTINCT batch_id) AS batch_count
            FROM motion_records
            GROUP BY session_id
            ORDER BY last_received_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def count_samples(filters: dict) -> int:
    where, params = filters_where(filters)
    with connect_db() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS total FROM motion_records {where}", params).fetchone()
    return int(row["total"])


def fetch_samples(filters: dict, limit: int, offset: int) -> list[dict]:
    where, params = filters_where(filters)
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                session_id,
                batch_id,
                sample_index,
                sample_time_us,
                accel_x_raw,
                accel_y_raw,
                accel_z_raw,
                gyro_x_raw,
                gyro_y_raw,
                gyro_z_raw,
                received_at
            FROM motion_records
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows]


def iterate_samples(filters: dict):
    where, params = filters_where(filters)
    conn = connect_db()
    cursor = conn.execute(
        f"""
        SELECT
            id,
            session_id,
            batch_id,
            sample_index,
            sample_time_us,
            accel_x_raw,
            accel_y_raw,
            accel_z_raw,
            gyro_x_raw,
            gyro_y_raw,
            gyro_z_raw,
            received_at
        FROM motion_records
        {where}
        ORDER BY session_id, batch_id, sample_index
        """,
        params,
    )
    try:
        for row in cursor:
            yield row
    finally:
        cursor.close()
        conn.close()


def stream_samples_csv(filters: dict):
    header = [
        "id",
        "session_id",
        "batch_id",
        "sample_index",
        "sample_time_us",
        "received_at",
        "accel_x_raw",
        "accel_y_raw",
        "accel_z_raw",
        "gyro_x_raw",
        "gyro_y_raw",
        "gyro_z_raw",
    ]
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    yield buf.getvalue()

    for row in iterate_samples(filters):
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                row["id"],
                row["session_id"],
                row["batch_id"],
                row["sample_index"],
                row["sample_time_us"],
                row["received_at"],
                row["accel_x_raw"],
                row["accel_y_raw"],
                row["accel_z_raw"],
                row["gyro_x_raw"],
                row["gyro_y_raw"],
                row["gyro_z_raw"],
            ]
        )
        yield buf.getvalue()


def clear_database() -> None:
    with connect_db() as conn:
        conn.execute("DELETE FROM motion_records")
        conn.commit()
