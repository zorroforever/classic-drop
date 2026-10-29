import subprocess
from pathlib import Path
from threading import Event

import pytest

from classic_drop.engine import ClassicDropEngine, OperationCancelledError
from classic_drop.media import collect_audio
from iOpenPod.app.library_write import WriteProgress
from tests.classic_drop.test_engine import connected  # noqa: F401
from tests.classic_drop.test_media import media_file
from tests.iOpenPod.app.services.test_library_resources import Device


def test_enumeration_is_cancellable_and_reports_discovery(tmp_path: Path) -> None:
    (tmp_path / "one.mp3").touch()
    observed: list[int] = []
    checkpoints: list[bool] = []
    assert collect_audio(
        (tmp_path,),
        checkpoint=lambda: checkpoints.append(True),
        discovered=lambda n: observed.append(n),
    ) == (tmp_path / "one.mp3",)
    assert observed == [1]
    assert checkpoints


def test_preview_reports_completed_file_and_keeps_old_queue_on_cancel(
    connected: tuple[Device, ClassicDropEngine],  # noqa: F811
    tmp_path: Path,
) -> None:
    _device, engine = connected
    old = engine.preview((media_file(tmp_path),), Event())
    cancelled = Event()
    events: list[WriteProgress] = []

    def progress(event: WriteProgress) -> None:
        events.append(event)
        if event.phase == "inspect" and event.completed == 1:
            cancelled.set()

    engine.progress = progress
    with pytest.raises(OperationCancelledError):
        engine.preview((old[0].path, media_file(tmp_path, "lossless.m4a")), cancelled)
    assert tuple(engine._entries.values()) == old
    assert set(engine._songs) == {old[0].token}
    assert any(e.phase == "scan" for e in events)


def test_single_file_preview_finishes_count(
    connected: tuple[Device, ClassicDropEngine],  # noqa: F811
    tmp_path: Path,
) -> None:
    _device, engine = connected
    events: list[WriteProgress] = []
    engine.progress = events.append
    engine.preview((media_file(tmp_path),), Event())
    assert events[-1].phase == "inspect"
    assert events[-1].completed == events[-1].total == 1


def test_flac_preview_forwards_measured_transcoding_progress(
    connected: tuple[Device, ClassicDropEngine],  # noqa: F811
    tmp_path: Path,
) -> None:
    _device, engine = connected
    source = media_file(tmp_path, "lossless.m4a")
    target = tmp_path / "音乐.flac"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(source), "-c:a", "flac", str(target)],
        check=True,
    )
    events: list[WriteProgress] = []
    engine.progress = events.append
    entries = engine.preview((target,), Event())
    assert entries[0].mode == "convert"
    converting = [
        e.active_items[0].progress
        for e in events
        if e.phase == "media.converting" and e.active_items
    ]
    assert converting
    assert any(
        p.duration_seconds and p.processed_seconds is not None for p in converting
    )
