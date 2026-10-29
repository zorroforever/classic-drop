"""Check painted album contrast and live placeholder palette changes."""

from PySide6.QtCore import QEvent, QRect
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionViewItem

from classic_drop.window import MainWindow
from iPodDB.library import Track
from tests.classic_drop.test_shell import active_library


def test_selected_album_metadata_uses_highlighted_text(app: QApplication) -> None:
    window = MainWindow(start_worker=False)
    track = Track(
        track_id=1, title="Song", artist="Artist", album="Album", length_ms=60000
    )
    window._active = active_library((track,))
    window._update_library_table()
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 190, 258)
    option.state = QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_Enabled
    option.palette.setColor(QPalette.ColorRole.Highlight, QColor("#ff0000"))
    option.palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#00ff00"))
    option.palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#0000ff"))
    image = QImage(190, 258, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    try:
        window.album_grid.itemDelegate().paint(
            painter, option, window.album_grid.model().index(0, 0)
        )
    finally:
        painter.end()
        window.close()
    assert any(
        image.pixelColor(x, y) == QColor("#00ff00")
        for y in range(208, 248)
        for x in range(12, 178)
    )


def test_open_album_placeholder_repaints_when_host_palette_changes(
    app: QApplication,
) -> None:
    window = MainWindow(start_worker=False)
    track = Track(
        track_id=1, title="Song", artist="Artist", album="Album", length_ms=60000
    )
    window._active = active_library((track,))
    window._update_library_table()
    window._set_library_mode("album")
    window._open_album(window.album_grid.item(0))
    original = app.palette()
    changed = QPalette(original)
    color = QColor("#fefdfc")
    changed.setColor(QPalette.ColorRole.PlaceholderText, color)
    try:
        app.setPalette(changed)
        QApplication.sendEvent(window, QEvent(QEvent.Type.ApplicationPaletteChange))
        image = window.album_detail_cover.pixmap().toImage()
        assert any(
            image.pixelColor(x, y) == color
            for y in range(image.height())
            for x in range(image.width())
        )
    finally:
        app.setPalette(original)
        window.close()
