"""Keep widget tests independent of Host preferences and other tests' translators."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from classic_drop.i18n import get_language_manager


@pytest.fixture(scope="module")
def app() -> QApplication:
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    return application


@pytest.fixture(autouse=True)
def isolated_language_settings(tmp_path: Path) -> Iterator[None]:
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    manager = get_language_manager(application, tmp_path / "qt-language-fixture")
    manager.set_language("en")
    try:
        yield
    finally:
        manager.close()
