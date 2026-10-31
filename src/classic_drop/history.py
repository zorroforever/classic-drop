"""Local receipts are hints; the current iPod library remains authoritative."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal, cast

type LibraryOperation = Literal["import", "playlist", "delete"]


class ImportHistory:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "imports.sqlite3"
        with self._connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS receipt (device TEXT, source_hash TEXT, location TEXT, size INTEGER, PRIMARY KEY(device, source_hash))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS import_run (id INTEGER PRIMARY KEY, device TEXT, recovery TEXT, restored INTEGER DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP, operation TEXT DEFAULT 'import')"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(import_run)")}
            if "operation" not in columns:
                db.execute(
                    "ALTER TABLE import_run ADD COLUMN operation TEXT DEFAULT 'import'"
                )
            if "kept" not in columns:
                db.execute("ALTER TABLE import_run ADD COLUMN kept INTEGER DEFAULT 0")

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
                "SELECT recovery FROM import_run WHERE device=? AND restored=0 AND kept=0 ORDER BY id DESC LIMIT 1",
                (device,),
            ).fetchone()
            return str(row[0]) if row else None

    def record_operation(
        self, device: str, recovery: str, operation: LibraryOperation
    ) -> None:
        with self._connection() as db:
            db.execute(
                "INSERT INTO import_run(device,recovery,operation) VALUES(?,?,?)",
                (device, recovery, operation),
            )

    def latest_operation(self, device: str) -> tuple[str, LibraryOperation] | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT recovery, operation FROM import_run WHERE device=? AND restored=0 AND kept=0 ORDER BY id DESC LIMIT 1",
                (device,),
            ).fetchone()
            return (str(row[0]), cast("LibraryOperation", row[1])) if row else None

    def keep_current(self, device: str, recovery: str) -> None:
        """Accept a completed removal without allowing undo across its baseline."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id, recovery, operation FROM import_run WHERE device=? AND restored=0 AND kept=0 ORDER BY id DESC LIMIT 1",
                (device,),
            ).fetchone()
            if row is None or (row[1], row[2]) != (recovery, "delete"):
                raise ValueError("The recovery record changed; reload")
            db.execute(
                "UPDATE import_run SET kept=1 WHERE device=? AND id<=? AND restored=0 AND kept=0",
                (device, row[0]),
            )
            db.execute("DELETE FROM receipt WHERE device=?", (device,))

    def restored(self, device: str, recovery: str) -> None:
        with self._connection() as db:
            db.execute(
                "UPDATE import_run SET restored=1 WHERE device=? AND recovery=?",
                (device, recovery),
            )
            db.execute("DELETE FROM receipt WHERE device=?", (device,))
