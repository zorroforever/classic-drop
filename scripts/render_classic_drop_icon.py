"""Render the Classic Drop SVGs into Qt and macOS application icons."""

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parents[1] / "src" / "classic_drop" / "assets"


def render_icon(name: str = "classic-drop") -> None:
    renderer = QSvgRenderer(str(ASSETS / f"{name}.svg"))
    if not renderer.isValid():
        raise ValueError("Invalid Classic Drop SVG")
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
    finally:
        painter.end()
    png = ASSETS / f"{name}.png"
    if not image.save(str(png)):
        raise OSError(f"Could not save {png}")
    with Image.open(png) as source:
        source.save(ASSETS / f"{name}.icns", format="ICNS")


if __name__ == "__main__":
    app = QGuiApplication(["classic-drop-icon"])
    render_icon()
    render_icon("classic-drop-glass")
