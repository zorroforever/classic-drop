"""Native palette and compact, reusable Classic Drop presentation widgets."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.icons import glyph_icon


def button(text: str, glyph: str) -> QPushButton:
    result = QPushButton(text)
    result.setProperty("classicDropGlyph", glyph)
    result.setProperty("classicDropGlyphSize", 18)
    result.setIcon(
        glyph_icon(
            glyph,
            18,
            QApplication.palette().color(QPalette.ColorRole.ButtonText),
        )
    )
    result.setMinimumHeight(32)
    return result


def tool(name: str, glyph: str) -> QToolButton:
    result = QToolButton()
    result.setProperty("classicDropGlyph", glyph)
    result.setProperty("classicDropGlyphSize", 19)
    result.setIcon(
        glyph_icon(
            glyph,
            19,
            QApplication.palette().color(QPalette.ColorRole.ButtonText),
        )
    )
    result.setToolTip(name)
    result.setAccessibleName(name)
    result.setFixedSize(32, 32)
    return result


def empty_state() -> tuple[QWidget, QLabel, QLabel]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.addStretch(1)
    title = QLabel()
    title.setObjectName("emptyTitle")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title.setWordWrap(True)
    font = QFont()
    font.setPointSize(15)
    font.setWeight(QFont.Weight.DemiBold)
    title.setFont(font)
    layout.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)
    detail = QLabel()
    detail.setObjectName("emptyDetail")
    detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
    detail.setWordWrap(True)
    detail.setMaximumWidth(440)
    layout.addWidget(detail, 0, Qt.AlignmentFlag.AlignHCenter)
    layout.addStretch(1)
    return page, title, detail


STYLE = """
            QLabel#muted, QLabel#emptyDetail { color: palette(placeholder-text); font-size: 9pt; }
            QLabel#emptyTitle { color: palette(text); }
            QTableWidget {
                background: palette(base);
                alternate-background-color: palette(alternate-base);
                border: 1px solid palette(mid);
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
            }
            QHeaderView::section {
                background: palette(button);
                padding: 8px 4px;
                border: 0;
                border-bottom: 1px solid palette(mid);
                color: palette(button-text);
                font-size: 9pt;
            }
            QProgressBar { border: 0; background: palette(midlight); border-radius: 2px; }
            QProgressBar::chunk { background: palette(highlight); border-radius: 2px; }
            QLabel#cover { background: palette(alternate-base); border: 1px solid palette(mid); }
            QPushButton#primary { font-weight: 600; }
        """
