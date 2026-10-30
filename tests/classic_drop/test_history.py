import sqlite3
from pathlib import Path

import pytest

from classic_drop.history import ImportHistory


def test_accepting_baseline_migrates_history_and_preserves_other_devices(
    tmp_path: Path,
) -> None:
    with sqlite3.connect(tmp_path / "imports.sqlite3") as db:
        db.execute(
            "CREATE TABLE import_run (id INTEGER PRIMARY KEY, device TEXT, recovery TEXT, restored INTEGER DEFAULT 0)"
        )
        db.execute("INSERT INTO import_run(device,recovery) VALUES('ipod','import')")
    history = ImportHistory(tmp_path)
    history.record_operation("ipod", "removal", "delete")
    history.record("other", "other-import", (("hash", "media", 3),))

    with pytest.raises(ValueError, match="recovery record changed"):
        history.keep_current("ipod", "old")
    assert history.latest("ipod") == "removal"
    history.keep_current("ipod", "removal")

    reopened = ImportHistory(tmp_path)
    assert reopened.latest("ipod") is None
    assert reopened.latest_operation("ipod") is None
    assert reopened.latest_operation("other") == ("other-import", "import")
    assert reopened.receipts("other") == {"hash": ("media", 3)}
    reopened.record_operation("ipod", "new-removal", "delete")
    reopened.restored("ipod", "new-removal")
    assert reopened.latest("ipod") is None
