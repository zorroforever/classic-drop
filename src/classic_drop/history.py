"""Local receipts are hints; the current iPod library remains authoritative."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class ImportHistory:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "imports.sqlite3"
        with self._connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS receipt (device TEXT, source_hash TEXT, location TEXT, size INTEGER, PRIMARY KEY(device, source_hash))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS import_run (id INTEGER PRIMARY KEY, device TEXT, recovery TEXT, restored INTEGER DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP)"
            )

    def _connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def receipts(self, device: str) -> dict[str, tuple[str, int]]:
        with self._connection() as db:
            return {
                sha: (path, size)
                for sha, path, size in db.execute(
                    "SELECT source_hash, location, size FROM receipt WHERE device=?",
                    (device,),
                )
            }

    def record(
        self, device: str, recovery: str, files: tuple[tuple[str, str, int], ...]
    ) -> None:
        with self._connection() as db:
            db.execute(
                "INSERT INTO import_run(device,recovery) VALUES(?,?)",
                (device, recovery),
            )
            db.executemany(
                "INSERT OR REPLACE INTO receipt VALUES(?,?,?,?)",
                ((device, sha, path, size) for sha, path, size in files),
            )

    def latest(self, device: str) -> str | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT recovery FROM import_run WHERE device=? AND restored=0 ORDER BY id DESC LIMIT 1",
                (device,),
            ).fetchone()
            return str(row[0]) if row else None

    def restored(self, device: str, recovery: str) -> None:
        with self._connection() as db:
            db.execute(
                "UPDATE import_run SET restored=1 WHERE device=? AND recovery=?",
                (device, recovery),
            )
            db.execute("DELETE FROM receipt WHERE device=?", (device,))
