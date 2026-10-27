"""Launch Classic Drop without the upstream full-library sync interface."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication

from classic_drop.window import MainWindow


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
    app = QApplication(sys.argv)
    app.setApplicationName("Classic Drop")
    app.setOrganizationName("Classic Drop")
    app.setStyle("Fusion")
    window = MainWindow(directory=directory)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
