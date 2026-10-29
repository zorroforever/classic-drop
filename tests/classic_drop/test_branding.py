"""Classic Drop exposes its own application identity and a visible Dock icon."""

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


def test_application_uses_classic_drop_identity_and_icon(app: QApplication) -> None:
    from classic_drop.branding import configure_application

    previous = (
        app.applicationName(),
        app.applicationDisplayName(),
        app.organizationName(),
        app.windowIcon(),
    )
    try:
        configure_application(app)

        assert app.applicationName() == "Classic Drop"
        assert app.applicationDisplayName() == "Classic Drop"
        assert app.organizationName() == "Classic Drop"
        assert not app.windowIcon().isNull()
    finally:
        app.setApplicationName(previous[0])
        app.setApplicationDisplayName(previous[1])
        app.setOrganizationName(previous[2])
        app.setWindowIcon(previous[3])


def test_icon_remains_visible_at_dock_sizes(app: QApplication) -> None:
    from classic_drop.branding import application_icon

    icon = application_icon()
    assert not icon.isNull()
    for size in (16, 32, 64, 128):
        image = (
            icon.pixmap(size, size)
            .toImage()
            .convertToFormat(QImage.Format.Format_ARGB32)
        )
        colors = {
            image.pixelColor(x, y).rgba()
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 0
        }
        assert len(colors) > 8
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() > 0
