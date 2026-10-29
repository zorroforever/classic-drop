"""Album grouping and compact artwork cards for the iPod library view."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from classic_drop.i18n import song_count, tr
from iOpenPod.GUI.presentation.icons import glyph_icon
from iPodDB.library import Track

ALBUM_ROLE = Qt.ItemDataRole.UserRole.value
ARTWORK_ROLE = ALBUM_ROLE + 1
CARD_SIZE = QSize(190, 258)


@dataclass(frozen=True, slots=True)
class AlbumSummary:
    key: str
    title: str
    artist: str
    year: int
    track_count: int
    duration_ms: int
    artwork_id: int
    tracks: tuple[Track, ...]


def group_albums(tracks: Iterable[Track]) -> tuple[AlbumSummary, ...]:
    grouped: dict[str, list[Track]] = {}
    for track in tracks:
        grouped.setdefault(track.album_key, []).append(track)

    albums = []
    for key, members in grouped.items():
        ordered = tuple(
            sorted(
                members,
                key=lambda track: (
                    track.metadata.disc_number,
                    track.track_number,
                    track.title.casefold(),
                ),
            )
        )
        representative = ordered[0]
        albums.append(
            AlbumSummary(
                key=key,
                title=representative.album,
                artist=representative.effective_album_artist,
                year=next((track.year for track in ordered if track.year > 0), 0),
                track_count=len(ordered),
                duration_ms=sum(max(0, track.length_ms) for track in ordered),
                artwork_id=next(
                    (track.artwork_id for track in ordered if track.artwork_id > 0), 0
                ),
                tracks=ordered,
            )
        )
    return tuple(
        sorted(
            albums, key=lambda album: (album.title.casefold(), album.artist.casefold())
        )
    )


class AlbumCardDelegate(QStyledItemDelegate):
    def __init__(
        self,
        request_artwork: Callable[[int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._request_artwork = request_artwork
        self._placeholders: dict[int, QPixmap] = {}

    def sizeHint(
        self,
        _option: QStyleOptionViewItem,
        _index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return CARD_SIZE

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        summary = index.data(ALBUM_ROLE)
        if not isinstance(summary, AlbumSummary):
            return

        rect = option.rect.adjusted(4, 4, -4, -4)
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        palette = option.palette
        painter.setPen(
            palette.color(
                QPalette.ColorRole.Highlight if selected else QPalette.ColorRole.Mid
            )
        )
        painter.setBrush(
            palette.color(
                QPalette.ColorRole.Highlight if selected else QPalette.ColorRole.Base
            )
        )
        painter.drawRoundedRect(rect, 5, 5)

        artwork_rect = QRect(rect.x() + 16, rect.y() + 12, rect.width() - 32, 142)
        pixmap = index.data(ARTWORK_ROLE)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            fitted = pixmap.scaled(
                artwork_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                artwork_rect.center().x() - fitted.width() // 2,
                artwork_rect.center().y() - fitted.height() // 2,
                fitted,
            )
        else:
            if summary.artwork_id > 0:
                self._request_artwork(summary.artwork_id)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(palette.color(QPalette.ColorRole.AlternateBase))
            painter.drawRect(artwork_rect)
            color = palette.color(QPalette.ColorRole.PlaceholderText)
            placeholder = self._placeholders.get(color.rgba())
            if placeholder is None:
                placeholder = glyph_icon("album", 110, color).pixmap(QSize(110, 110))
                self._placeholders[color.rgba()] = placeholder
            painter.drawPixmap(
                artwork_rect.center().x() - placeholder.width() // 2,
                artwork_rect.center().y() - placeholder.height() // 2,
                placeholder,
            )

        painter.setPen(
            palette.color(
                QPalette.ColorRole.HighlightedText
                if selected
                else QPalette.ColorRole.Text
            )
        )
        title_rect = QRect(
            rect.x() + 9, artwork_rect.bottom() + 10, rect.width() - 18, 38
        )
        painter.drawText(
            title_rect,
            int(
                Qt.AlignmentFlag.AlignHCenter
                | Qt.AlignmentFlag.AlignTop
                | Qt.TextFlag.TextWordWrap
            ),
            summary.title or tr("Unknown album"),
        )
        painter.setPen(
            palette.color(
                QPalette.ColorRole.HighlightedText
                if selected
                else QPalette.ColorRole.PlaceholderText
            )
        )
        detail = summary.artist
        if summary.year:
            detail = f"{detail}  ·  {summary.year}" if detail else str(summary.year)
        detail += f"\n{song_count(summary.track_count)}"
        painter.drawText(
            QRect(rect.x() + 9, title_rect.bottom() + 2, rect.width() - 18, 42),
            int(
                Qt.AlignmentFlag.AlignHCenter
                | Qt.AlignmentFlag.AlignTop
                | Qt.TextFlag.TextWordWrap
            ),
            detail,
        )
        painter.restore()
