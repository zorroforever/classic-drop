"""One persistent worker owns all media and device operations."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import cast

from PySide6.QtCore import QObject, Signal, Slot

from classic_drop.engine import ClassicDropEngine, PreviewEntry
from classic_drop.media import decode_cover
from iOpenPod.app.display_text import SourceText
from iOpenPod.app.models.artwork import ArtworkRequest
from iOpenPod.app.models.device import ActiveIPod, DeviceCandidateId
from iPodDB.library import LibrarySnapshot
from storage import HostPath
from storage.host_input import LocalHostFile


@dataclass(frozen=True)
class Reply:
    value: object
    active: ActiveIPod | None
    can_restore: bool


class Worker(QObject):
    succeeded = Signal(str, object)
    failed = Signal(str, object, object)
    progress = Signal(object)
    stopped = Signal()

    def __init__(self, directory: Path | None = None) -> None:
        super().__init__()
        self.directory = directory
        self.cancelled = Event()
        self.engine: ClassicDropEngine | None = None

    def reply(self, value: object = None) -> Reply:
        if self.engine is None:
            return Reply(value, None, False)
        active = self.engine.coordinator.active_ipod
        can_restore = bool(getattr(self.engine, "pending_recovery", None))
        try:
            can_restore |= bool(
                active and self.engine.history.latest(self.engine._identity())
            )
        except (OSError, ValueError, sqlite3.Error):
            logging.getLogger(__name__).exception("Could not read import history")
        return Reply(value, active, can_restore)

    @Slot(str, object)
    def execute(self, command: str, payload: object) -> None:
        try:
            if command == "close":
                if self.engine is not None:
                    self.engine.close()
                self.stopped.emit()
                return
            if self.engine is None:
                self.engine = ClassicDropEngine(
                    data_directory=self.directory,
                    progress=self.progress.emit,
                )
            engine = self.engine
            result: object
            if command == "discover":
                result = engine.discover()
            elif command == "select":
                result = engine.select(cast("DeviceCandidateId", payload))
            elif command == "preview":
                result = engine.preview(
                    cast("tuple[Path, ...]", payload), self.cancelled
                )
            elif command == "commit":
                result = engine.commit(
                    cast("tuple[PreviewEntry, ...]", payload), self.cancelled
                )
            elif command == "delete":
                track_ids, expected_library, device_id, database_sha256 = cast(
                    "tuple[tuple[int, ...], object, str, str]", payload
                )
                result = engine.remove_tracks(
                    track_ids,
                    self.cancelled,
                    cast("LibrarySnapshot", expected_library),
                    device_id,
                    database_sha256,
                )
            elif command == "restore":
                result = engine.restore_last(self.cancelled)
            elif command == "eject":
                engine.eject()
                result = None
            elif command == "discard":
                engine.discard()
                result = None
            elif command == "cover":
                data = LocalHostFile.observe(
                    HostPath(cast("Path", payload))
                ).read_bytes(
                    max_bytes=32 * 1024 * 1024,
                    checkpoint=lambda: engine._checkpoint(self.cancelled),
                )
                result = decode_cover(data)
            elif command == "artwork":
                result = engine.coordinator.load_artwork(
                    ArtworkRequest(int(cast("int", payload)), 320)
                )
            else:
                raise ValueError(f"Unknown operation: {command}")
            self.succeeded.emit(command, self.reply(result))
        except Exception as error:
            logging.getLogger(__name__).exception(
                "Classic Drop operation failed: %s", command
            )
            message: str
            if error.args and isinstance(error.args[0], SourceText):
                message = error.args[0]
            elif isinstance(error, ValueError) and "\n" in str(error):
                message = str(error)
            else:
                message = str(error) or type(error).__name__
            self.failed.emit(command, message, self.reply())
