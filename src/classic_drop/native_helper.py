"""Headless JSON Lines process. One worker owns SQLite, engine and device access."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Full, Queue
from threading import Event, Lock, Thread
from typing import BinaryIO, TextIO

from classic_drop.engine import ClassicDropEngine, OperationCancelledError
from classic_drop.native_backend import NativeBackend
from classic_drop.native_browser import build_index
from classic_drop.native_protocol import (
    MAX_MESSAGE,
    VERSION,
    Envelope,
    ProgressDTO,
    Request,
    Result,
)
from iOpenPod.app.library_write import WriteProgress


def progress_dto(progress: WriteProgress) -> ProgressDTO:
    fraction = None
    measurement = ""
    if progress.active_items:
        sample = progress.active_items[0].progress
        if sample.duration_seconds and sample.processed_seconds is not None:
            fraction = max(
                0.0, min(1.0, sample.processed_seconds / sample.duration_seconds)
            )
            measurement = "current_file"
        elif sample.total_bytes and sample.processed_bytes is not None:
            fraction = max(0.0, min(1.0, sample.processed_bytes / sample.total_bytes))
            measurement = "current_file"
    if fraction is None and progress.total and progress.completed is not None:
        fraction = max(0.0, min(1.0, progress.completed / progress.total))
        measurement = "stage"
    return ProgressDTO(
        progress.phase,
        str(progress.message),
        progress.completed,
        progress.total,
        progress.current_item,
        progress.unit,
        fraction,
        measurement,
    )


class HelperServer:
    def __init__(
        self,
        output: TextIO,
        directory: Path | None,
        *,
        engine_factory: Callable[[], ClassicDropEngine] | None = None,
    ) -> None:
        self.output = output
        self.directory = directory
        self.engine_factory = engine_factory or (
            lambda: ClassicDropEngine(data_directory=self.directory)
        )
        self.queue: Queue[tuple[Request, Event]] = Queue(maxsize=64)
        self.lock = Lock()
        self.output_lock = Lock()
        self.events: dict[str, Event] = {}
        self.sequence = 0
        self.generation = ""
        self.seen: set[str] = set()
        self.output_failed = Event()
        self.preparations: list[Thread] = []

    def emit(
        self,
        request_id: str,
        event: str,
        *,
        result: Result | None = None,
        progress: ProgressDTO | None = None,
        code: str = "",
        detail: str = "",
    ) -> None:
        with self.output_lock:
            if self.output_failed.is_set():
                return
            self.sequence += 1
            envelope = Envelope(
                request_id,
                event,
                self.generation,
                self.sequence,
                result,
                progress,
                code,
                detail,
            )
            data = json.dumps(
                asdict(envelope), ensure_ascii=False, separators=(",", ":")
            )
            if len(data.encode("utf-8")) > MAX_MESSAGE:
                data = json.dumps(
                    asdict(
                        Envelope(
                            request_id,
                            "error",
                            self.generation,
                            self.sequence,
                            code="response_too_large",
                            detail="Narrow the query or use a smaller page",
                        )
                    )
                )
            try:
                self.output.write(data + "\n")
                self.output.flush()
            except OSError:
                self.output_failed.set()
                with self.lock:
                    for cancelled in self.events.values():
                        cancelled.set()
                logging.getLogger(__name__).warning(
                    "Native UI transport closed; cancelling at safe checkpoints"
                )

    def run_worker(self) -> None:
        try:
            engine = self.engine_factory()
        except Exception as error:
            logging.getLogger(__name__).exception(
                "Could not initialize the native worker"
            )
            while True:
                request, _cancelled = self.queue.get()
                self.emit(request.id, "error", code="startup_failed", detail=str(error))
                self.queue.task_done()
                if request.command == "close":
                    return
        try:
            self._serve(engine)
        finally:
            for preparation in self.preparations:
                preparation.join()
            engine.close()

    def _serve(self, engine: ClassicDropEngine) -> None:
        backend = NativeBackend(engine)
        self.generation = backend.generation
        while True:
            request, cancelled = self.queue.get()
            pending: ProgressDTO | None = None
            last_time = 0.0
            last_phase = ""

            def report(value: WriteProgress, request_id: str = request.id) -> None:
                nonlocal pending, last_time, last_phase
                pending = progress_dto(value)
                now = time.monotonic()
                if now - last_time >= 0.1 or value.phase != last_phase:
                    self.emit(request_id, "progress", progress=pending)
                    pending = None
                    last_time, last_phase = now, value.phase

            preparation_started = False
            engine.progress = report
            try:
                if request.command == "close":
                    self.emit(request.id, "result", result=backend._result())
                    return
                if request.command == "prepare_browser":
                    self._prepare_browser(backend, request, cancelled)
                    preparation_started = True
                    continue
                result = backend.execute(request, cancelled)
                self.generation = backend.generation
                if pending:
                    self.emit(request.id, "progress", progress=pending)
                self.emit(request.id, "result", result=result)
            except Exception as error:
                logging.getLogger(__name__).exception(
                    "Native operation %s failed", request.command
                )
                try:
                    result = backend._result()
                    self.generation = backend.generation
                except Exception:
                    result = None
                if pending:
                    self.emit(request.id, "progress", progress=pending)
                code = (
                    "cancelled"
                    if isinstance(error, OperationCancelledError)
                    else "recovery_required"
                    if engine.pending_recovery
                    else "operation_failed"
                )
                self.emit(
                    request.id, "error", result=result, code=code, detail=str(error)
                )
            finally:
                with self.lock:
                    if not preparation_started:
                        self.events.pop(request.id, None)
                self.queue.task_done()

    def _prepare_browser(
        self, backend: NativeBackend, request: Request, cancelled: Event
    ) -> None:
        active, generation, result = backend.browser_source(request)

        def run() -> None:
            last_percent = -1

            def report(completed: int, total: int) -> None:
                nonlocal last_percent
                percent = completed * 100 // max(1, total)
                if percent != last_percent:
                    last_percent = percent
                    self.emit(
                        request.id,
                        "progress",
                        progress=ProgressDTO(
                            "browser.index",
                            "Preparing complete Library metadata",
                            completed,
                            total,
                            "",
                            "tracks",
                            percent / 100,
                            "stage",
                        ),
                    )

            try:
                index = build_index(active.library, cancelled, report)
                if not backend.publish_browser(active, generation, index, cancelled):
                    raise InterruptedError("Browser preparation cancelled")
                self.emit(request.id, "result", result=result)
            except Exception as error:
                self.emit(
                    request.id,
                    "error",
                    code="cancelled"
                    if cancelled.is_set() or isinstance(error, InterruptedError)
                    else "operation_failed",
                    detail=str(error),
                )
            finally:
                with self.lock:
                    self.events.pop(request.id, None)

        thread = Thread(target=run, name="classic-drop-browser")
        self.preparations = [
            worker for worker in self.preparations if worker.is_alive()
        ]
        self.preparations.append(thread)
        thread.start()

    def _invalid_request_id(self, data: bytes) -> str:
        """Recover only a valid, fresh envelope ID after strict payload rejection."""
        if len(data) > MAX_MESSAGE:
            return ""
        try:
            raw = json.loads(data)
        except (ValueError, TypeError, RecursionError):
            return ""
        if (
            not isinstance(raw, dict)
            or type(raw.get("version")) is not int
            or raw["version"] != VERSION
        ):
            return ""
        identity = raw.get("id")
        if not isinstance(identity, str) or not 1 <= len(identity) <= 16384:
            return ""
        try:
            identity.encode("utf-8")
        except UnicodeEncodeError:
            return ""
        if identity in self.seen or len(self.seen) >= 100000:
            return ""
        # Even rejected commands consume their identity: a later frame must not
        # replay it or finish a different in-flight command with the same ID.
        self.seen.add(identity)
        return identity

    def run(self, stream: BinaryIO) -> None:
        worker = Thread(target=self.run_worker, name="classic-drop-engine")
        worker.start()
        closing = False
        for line in iter(lambda: stream.readline(MAX_MESSAGE + 2), b""):
            try:
                request = Request.decode(line)
                if request.command == "cancel":
                    with self.lock:
                        target = self.events.get(request.token)
                        if target:
                            target.set()
                    self.emit(request.id, "accepted")
                    continue
                if request.command == "close":
                    with self.lock:
                        for event in self.events.values():
                            event.set()
                    self.queue.put((request, Event()))
                    closing = True
                    break
                if request.id in self.seen:
                    raise ValueError(
                        "Request ID already used; commands are never replayed"
                    )
                if len(self.seen) >= 100000:
                    raise ValueError("Session request limit reached; restart when idle")
                self.seen.add(request.id)
                event = Event()
                with self.lock:
                    self.events[request.id] = event
                try:
                    self.queue.put_nowait((request, event))
                except Full:
                    with self.lock:
                        self.events.pop(request.id, None)
                    self.emit(
                        request.id, "error", code="busy", detail="Command queue is full"
                    )
            except (ValueError, TypeError) as error:
                self.emit(
                    self._invalid_request_id(line),
                    "error",
                    code="invalid_request",
                    detail=str(error),
                )
                if len(line) > MAX_MESSAGE:
                    break
        if not closing:
            with self.lock:
                for event in self.events.values():
                    event.set()
            self.queue.put((Request("_close", "close"), Event()))
        worker.join()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-directory", type=Path)
    options = parser.parse_args()
    directory = (
        options.data_directory
        or Path.home() / "Library/Application Support/Classic Drop"
    )
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            RotatingFileHandler(
                directory / "classic-drop-native.log",
                maxBytes=2 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            ),
            logging.StreamHandler(sys.stderr),
        ],
    )
    output = sys.stdout
    sys.stdout = sys.stderr
    HelperServer(output, directory).run(sys.stdin.buffer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
