"""Classic Drop's application identity and original application artwork."""

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

ASSET_DIRECTORY = Path(__file__).with_name("assets")


def application_icon() -> QIcon:
    """Load the packaged high-resolution icon, including source checkout launches."""
    return QIcon(str(ASSET_DIRECTORY / "classic-drop.png"))


def configure_application(application: QApplication) -> None:
    application.setApplicationName("Classic Drop")
    application.setApplicationDisplayName("Classic Drop")
    application.setOrganizationName("Classic Drop")
    application.setWindowIcon(application_icon())
