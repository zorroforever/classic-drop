"""Launch Classic Drop without the upstream full-library sync interface."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication

from classic_drop.branding import configure_application
from classic_drop.window import MainWindow
from iOpenPod.GUI.presentation.display import configure_display


def main() -> int:
    directory = Path.home() / "Library/Application Support/Classic Drop"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "classic-drop.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    configure_display()
    app = QApplication(sys.argv)
    configure_application(app)
    window = MainWindow(directory=directory)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
