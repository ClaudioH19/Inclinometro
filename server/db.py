from __future__ import annotations

import csv
import os
import sqlite3
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("SQLITE_PATH", DATA_DIR / "clinostat.db"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA foreign_keys=ON;")
    return connection


def initialize_db() -> None:
    with connect_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                trial_number INTEGER NOT NULL,
                label TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                first_sample_time_us INTEGER NOT NULL,
                last_sample_time_us INTEGER NOT NULL,
                last_batch_id INTEGER NOT NULL,
                batch_count INTEGER NOT NULL DEFAULT 0,
                sample_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(device_id, trial_number)
            );

            CREATE TABLE IF NOT EXISTS motion_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trial_id INTEGER NOT NULL REFERENCES trials(id) ON DELETE CASCADE,
                device_id TEXT NOT NULL,
                trial_number INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                received_at TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                first_sample_time_us INTEGER NOT NULL,
                last_sample_time_us INTEGER NOT NULL,
                UNIQUE(device_id, trial_number, batch_id)
            );

            CREATE TABLE IF NOT EXISTS motion_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_db_id INTEGER NOT NULL REFERENCES motion_batches(id) ON DELETE CASCADE,
                trial_id INTEGER NOT NULL REFERENCES trials(id) ON DELETE CASCADE,
                device_id TEXT NOT NULL,
                trial_number INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                sample_index INTEGER NOT NULL,
                sample_time_us INTEGER NOT NULL,
                accel_x_raw INTEGER NOT NULL,
                accel_y_raw INTEGER NOT NULL,
                accel_z_raw INTEGER NOT NULL,
                gyro_x_raw INTEGER NOT NULL,
                gyro_y_raw INTEGER NOT NULL,
                gyro_z_raw INTEGER NOT NULL,
                UNIQUE(device_id, trial_number, batch_id, sample_index)
            );

            CREATE INDEX IF NOT EXISTS idx_trials_device
            ON trials(device_id, trial_number);

            CREATE INDEX IF NOT EXISTS idx_batches_trial
            ON motion_batches(device_id, trial_number, batch_id);

            CREATE INDEX IF NOT EXISTS idx_samples_trial
            ON motion_samples(device_id, trial_number, batch_id, sample_index);
            """
        )


def latest_trial(connection: sqlite3.Connection, device_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT id, trial_number, last_batch_id, last_sample_time_us
        FROM trials
        WHERE device_id = ?
        ORDER BY trial_number DESC
        LIMIT 1
        """,
        (device_id,),
    ).fetchone()


def latest_batch(connection: sqlite3.Connection, device_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT trial_id, trial_number, batch_id, first_sample_time_us, last_sample_time_us
        FROM motion_batches
        WHERE device_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (device_id,),
    ).fetchone()


def create_trial(
    connection: sqlite3.Connection,
    device_id: str,
    trial_number: int,
    received_at: str,
    first_sample_time_us: int,
    last_sample_time_us: int,
    batch_id: int,
) -> tuple[int, int]:
    cursor = connection.execute(
        """
        INSERT INTO trials (
            device_id,
            trial_number,
            started_at,
            ended_at,
            first_sample_time_us,
            last_sample_time_us,
            last_batch_id,
            batch_count,
            sample_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
        """,
        (
            device_id,
            trial_number,
            received_at,
            received_at,
            first_sample_time_us,
            last_sample_time_us,
            batch_id,
        ),
    )
    return cursor.lastrowid, trial_number


def resolve_trial(
    connection: sqlite3.Connection,
    device_id: str,
    batch_id: int,
    first_sample_time_us: int,
    last_sample_time_us: int,
    received_at: str,
) -> tuple[int, int]:
    previous_batch = latest_batch(connection, device_id)
    if previous_batch is not None:
        is_same_batch = (
            batch_id == previous_batch["batch_id"]
            and first_sample_time_us == previous_batch["first_sample_time_us"]
            and last_sample_time_us == previous_batch["last_sample_time_us"]
        )
        if is_same_batch:
            return previous_batch["trial_id"], previous_batch["trial_number"]

    row = latest_trial(connection, device_id)
    if row is None:
        return create_trial(
            connection,
            device_id,
            1,
            received_at,
            first_sample_time_us,
            last_sample_time_us,
            batch_id,
        )

    if batch_id <= row["last_batch_id"] or first_sample_time_us <= row["last_sample_time_us"]:
        return create_trial(
            connection,
            device_id,
            row["trial_number"] + 1,
            received_at,
            first_sample_time_us,
            last_sample_time_us,
            batch_id,
        )

    return row["id"], row["trial_number"]


def update_trial_after_batch(
    connection: sqlite3.Connection,
    trial_id: int,
    received_at: str,
    last_sample_time_us: int,
    batch_id: int,
    sample_count: int,
) -> None:
    connection.execute(
        """
        UPDATE trials
        SET ended_at = ?,
            last_sample_time_us = ?,
            last_batch_id = ?,
            batch_count = batch_count + 1,
            sample_count = sample_count + ?
        WHERE id = ?
        """,
        (received_at, last_sample_time_us, batch_id, sample_count, trial_id),
    )


def save_motion_batch(device_id: str, batch_id: int, samples: list[list[int]]) -> int:
    received_at = utc_now_iso()
    first_sample_time_us = samples[0][0]
    last_sample_time_us = samples[-1][0]

    with connect_db() as connection:
        trial_id, trial_number = resolve_trial(
            connection,
            device_id,
            batch_id,
            first_sample_time_us,
            last_sample_time_us,
            received_at,
        )

        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO motion_batches (
                trial_id,
                device_id,
                trial_number,
                batch_id,
                received_at,
                sample_count,
                first_sample_time_us,
                last_sample_time_us
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trial_id,
                device_id,
                trial_number,
                batch_id,
                received_at,
                len(samples),
                first_sample_time_us,
                last_sample_time_us,
            ),
        )

        if cursor.rowcount == 0:
            return trial_number

        batch_db_id = cursor.lastrowid
        connection.executemany(
            """
            INSERT INTO motion_samples (
                batch_db_id,
                trial_id,
                device_id,
                trial_number,
                batch_id,
                sample_index,
                sample_time_us,
                accel_x_raw,
                accel_y_raw,
                accel_z_raw,
                gyro_x_raw,
                gyro_y_raw,
                gyro_z_raw
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    batch_db_id,
                    trial_id,
                    device_id,
                    trial_number,
                    batch_id,
                    sample_index,
                    sample[0],
                    sample[1],
                    sample[2],
                    sample[3],
                    sample[4],
                    sample[5],
                    sample[6],
                )
                for sample_index, sample in enumerate(samples)
            ],
        )

        update_trial_after_batch(
            connection,
            trial_id,
            received_at,
            last_sample_time_us,
            batch_id,
            len(samples),
        )
        connection.commit()

    return trial_number


def apply_filters(
    filters: dict,
    sample_alias: str = "s",
    batch_alias: str = "b",
    trial_alias: str = "t",
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []

    if filters.get("device_id"):
        clauses.append(f"{sample_alias}.device_id = ?")
        params.append(filters["device_id"])
    if filters.get("trial_id"):
        clauses.append(f"{sample_alias}.trial_id = ?")
        params.append(filters["trial_id"])
    if filters.get("trial_number"):
        clauses.append(f"{sample_alias}.trial_number = ?")
        params.append(filters["trial_number"])
    if filters.get("received_after"):
        clauses.append(f"{batch_alias}.received_at >= ?")
        params.append(filters["received_after"])
    if filters.get("received_before"):
        clauses.append(f"{batch_alias}.received_at <= ?")
        params.append(filters["received_before"])
    if filters.get("started_after"):
        clauses.append(f"{trial_alias}.started_at >= ?")
        params.append(filters["started_after"])
    if filters.get("started_before"):
        clauses.append(f"{trial_alias}.started_at <= ?")
        params.append(filters["started_before"])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


def list_devices() -> list[dict]:
    with connect_db() as connection:
        rows = connection.execute(
            """
            SELECT
                device_id,
                COUNT(*) AS trial_count,
                SUM(sample_count) AS sample_count,
                MIN(started_at) AS started_at,
                MAX(ended_at) AS ended_at
            FROM trials
            GROUP BY device_id
            ORDER BY device_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_trials(device_id: str | None = None) -> list[dict]:
    with connect_db() as connection:
        if device_id:
            rows = connection.execute(
                """
                SELECT id, device_id, trial_number, label, started_at, ended_at, batch_count, sample_count
                FROM trials
                WHERE device_id = ?
                ORDER BY trial_number DESC
                """,
                (device_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, device_id, trial_number, label, started_at, ended_at, batch_count, sample_count
                FROM trials
                ORDER BY device_id, trial_number DESC
                """
            ).fetchall()
    return [dict(row) for row in rows]


def set_trial_label(trial_id: int, label: str | None) -> bool:
    with connect_db() as connection:
        cursor = connection.execute(
            "UPDATE trials SET label = ? WHERE id = ?",
            (label.strip() if label else None, trial_id),
        )
        connection.commit()
    return cursor.rowcount > 0


def clear_database() -> None:
    with connect_db() as connection:
        connection.execute("DELETE FROM motion_samples")
        connection.execute("DELETE FROM motion_batches")
        connection.execute("DELETE FROM trials")
        connection.commit()


def iter_samples(filters: dict) -> Iterator[sqlite3.Row]:
    where_sql, params = apply_filters(filters)
    query = f"""
        SELECT
            s.device_id,
            s.trial_id,
            s.trial_number,
            s.batch_id,
            s.sample_index,
            s.sample_time_us,
            s.accel_x_raw,
            s.accel_y_raw,
            s.accel_z_raw,
            s.gyro_x_raw,
            s.gyro_y_raw,
            s.gyro_z_raw,
            b.received_at,
            COALESCE(t.label, '') AS trial_label
        FROM motion_samples s
        JOIN motion_batches b ON b.id = s.batch_db_id
        JOIN trials t ON t.id = s.trial_id
        {where_sql}
        ORDER BY s.device_id, s.trial_number, s.batch_id, s.sample_index
    """
    connection = connect_db()
    cursor = connection.execute(query, params)
    try:
        for row in cursor:
            yield row
    finally:
        cursor.close()
        connection.close()


def fetch_samples_page(filters: dict, limit: int = 500, offset: int = 0) -> list[dict]:
    where_sql, params = apply_filters(filters)
    with connect_db() as connection:
        rows = connection.execute(
            f"""
            SELECT
                s.device_id,
                s.trial_id,
                s.trial_number,
                s.batch_id,
                s.sample_index,
                s.sample_time_us,
                s.accel_x_raw,
                s.accel_y_raw,
                s.accel_z_raw,
                s.gyro_x_raw,
                s.gyro_y_raw,
                s.gyro_z_raw,
                b.received_at,
                COALESCE(t.label, '') AS trial_label
            FROM motion_samples s
            JOIN motion_batches b ON b.id = s.batch_db_id
            JOIN trials t ON t.id = s.trial_id
            {where_sql}
            ORDER BY s.id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return [dict(row) for row in rows]


def count_samples(filters: dict) -> int:
    where_sql, params = apply_filters(filters)
    with connect_db() as connection:
        row = connection.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM motion_samples s
            JOIN motion_batches b ON b.id = s.batch_db_id
            JOIN trials t ON t.id = s.trial_id
            {where_sql}
            """,
            params,
        ).fetchone()
    return int(row["total"])


def stream_samples_csv(filters: dict) -> Iterator[str]:
    header = [
        "device_id",
        "trial_id",
        "trial_number",
        "trial_label",
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

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    yield buffer.getvalue()

    for row in iter_samples(filters):
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                row["device_id"],
                row["trial_id"],
                row["trial_number"],
                row["trial_label"],
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
        yield buffer.getvalue()
