"""DB connection and helpers for the Actual Budget Normalizer."""

import sqlite3
from typing import Any


def get_db(db_path: str) -> "DBHelper":
    """Get a DBHelper instance for the given database path."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return DBHelper(conn)


class DBHelper:
    """Helper class for database operations in the Actual Budget Normalizer."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize the DBHelper with a SQLite connection."""
        self.conn = conn

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        """Retrieve the status and metadata for a job by its ID."""
        row = self.conn.execute(
            "SELECT status, created_at, completed_at, error FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def get_job_output_path(self, job_id: str) -> str | None:
        """Retrieve the output file path for a job by its ID."""
        row = self.conn.execute(
            "SELECT output_path FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        return row["output_path"]
