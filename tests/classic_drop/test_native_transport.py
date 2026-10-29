import io
from threading import Event

from classic_drop.native_helper import HelperServer


def test_progress_transport_failure_requests_cancel_without_raising() -> None:
    class Disconnected(io.StringIO):
        def write(self, text: str) -> int:
            raise BrokenPipeError("UI exited")

    server = HelperServer(Disconnected(), None)
    cancelled = Event()
    server.events["operation"] = cancelled
    server.emit("operation", "progress")
    assert cancelled.is_set()
    # Further progress in a noncancellable phase remains safe after IPC loss.
    server.emit("operation", "progress")
