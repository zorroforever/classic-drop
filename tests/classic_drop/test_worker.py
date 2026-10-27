import sqlite3
from types import SimpleNamespace

from classic_drop.worker import Worker


def test_reply_still_emits_when_receipt_database_is_unavailable():
    def unavailable(_identity):
        raise sqlite3.OperationalError("database is locked")

    worker = Worker()
    worker.engine = SimpleNamespace(
        coordinator=SimpleNamespace(active_ipod=object()),
        history=SimpleNamespace(latest=unavailable),
        _identity=lambda: "device",
        discard=lambda: None,
    )
    replies = []
    worker.succeeded.connect(lambda command, reply: replies.append((command, reply)))
    worker.execute("discard", None)
    assert len(replies) == 1
    assert not replies[0][1].can_restore
