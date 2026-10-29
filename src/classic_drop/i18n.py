"""Runtime language selection and display-text translation for Classic Drop."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from PySide6.QtCore import (
    QCoreApplication,
    QLocale,
    QObject,
    QSettings,
    QTranslator,
    Signal,
)

from iOpenPod.app.display_text import SourceText

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

CATALOG_DIRECTORY = Path(__file__).with_name("translations")
SUPPORTED_LANGUAGES = ("en", "zh_CN", "ja_JP")
SYSTEM_LANGUAGE = "system"


def resolve_language(preferences: list[str] | tuple[str, ...]) -> str:
    """Choose the first supported locale from the system's ordered preferences."""

    return _resolve_supported_language(preferences) or "en"


def resolve_system_language(
    qt_preferences: list[str] | tuple[str, ...],
    apple_preferences: list[str] | tuple[str, ...],
) -> str:
    """Prefer Qt's locale list, falling back to macOS global language preferences."""

    return (
        _resolve_supported_language(qt_preferences)
        or _resolve_supported_language(apple_preferences)
        or "en"
    )


def _resolve_supported_language(
    preferences: list[str] | tuple[str, ...],
) -> str | None:
    for preference in preferences:
        parts = preference.replace("_", "-").split("-")
        language = parts[0].casefold()
        script = next((part.casefold() for part in parts[1:] if len(part) == 4), None)
        region = next((part.upper() for part in parts[1:] if len(part) in (2, 3)), None)
        if language == "en":
            return "en"
        if language == "ja":
            return "ja_JP"
        if language == "zh":
            if script == "hant" or region in {"TW", "HK", "MO"}:
                continue
            if script == "hans" or region in {"CN", "SG"} or len(parts) == 1:
                return "zh_CN"
    return None


def _apple_language_preferences() -> tuple[str, ...]:
    if sys.platform != "darwin":
        return ()
    try:
        from Foundation import NSUserDefaults  # type: ignore[import-untyped]
    except ImportError:
        return ()
    preferences = NSUserDefaults.standardUserDefaults().arrayForKey_("AppleLanguages")
    return tuple(str(language) for language in preferences or ())


def _system_language() -> str:
    return resolve_system_language(
        QLocale.system().uiLanguages(), _apple_language_preferences()
    )


class LanguageManager(QObject):
    """Persist the selected language and install its compiled Qt catalog."""

    languageChanged = Signal(str)

    def __init__(
        self, application: QApplication, directory: Path | None = None
    ) -> None:
        super().__init__(application)
        self._application = application
        self._previous_locale = QLocale()
        self._translator: QTranslator | None = None
        if directory is None:
            self._settings = QSettings("Classic Drop", "Classic Drop")
        else:
            directory.mkdir(parents=True, exist_ok=True)
            self._settings = QSettings(
                str(directory / "settings.ini"), QSettings.Format.IniFormat
            )

        saved = self._settings.value("language", "")
        self._follows_system = not (
            isinstance(saved, str) and saved in SUPPORTED_LANGUAGES
        )
        self._language = (
            _system_language()
            if self._follows_system
            else str(saved)
        )
        self._install(self._language, emit=False)

    @property
    def language(self) -> str:
        return self._language

    @property
    def follows_system(self) -> bool:
        return self._follows_system

    def set_language(self, language_tag: str) -> None:
        if language_tag not in (*SUPPORTED_LANGUAGES, SYSTEM_LANGUAGE):
            raise ValueError(f"Unsupported language: {language_tag}")
        follows_system = language_tag == SYSTEM_LANGUAGE
        language = _system_language() if follows_system else language_tag
        if language == self._language and follows_system == self._follows_system:
            return
        self._follows_system = follows_system
        self._install(language, emit=True)
        self._settings.setValue("language", language_tag)
        self._settings.sync()

    def close(self) -> None:
        self._remove_translator()
        QLocale.setDefault(self._previous_locale)
        _MANAGERS.pop(self._application, None)

    def _install(self, language_tag: str, *, emit: bool) -> None:
        translator: QTranslator | None = None
        if language_tag != "en":
            translator = QTranslator()
            catalog = CATALOG_DIRECTORY / f"classic_drop_{language_tag}.qm"
            if not translator.load(str(catalog)):
                translator.deleteLater()
                raise RuntimeError(f"Could not load translation catalog: {catalog}")

        self._remove_translator()
        self._language = language_tag
        QLocale.setDefault(QLocale(language_tag))
        if translator is not None:
            self._application.installTranslator(translator)
            self._translator = translator
        if emit:
            self.languageChanged.emit(language_tag)

    def _remove_translator(self) -> None:
        if self._translator is not None:
            self._application.removeTranslator(self._translator)
            self._translator.deleteLater()
            self._translator = None


_MANAGERS: WeakKeyDictionary[QApplication, LanguageManager] = WeakKeyDictionary()


def get_language_manager(
    application: QApplication, directory: Path | None = None
) -> LanguageManager:
    manager = _MANAGERS.get(application)
    if manager is None:
        manager = LanguageManager(application, directory)
        _MANAGERS[application] = manager
    return manager


def tr(source: str) -> str:
    return QCoreApplication.translate("ClassicDrop", source)


def song_count(count: int) -> str:
    count = max(0, count)
    translated = QCoreApplication.translate("ClassicDrop", "%n song(s)", None, count)
    source_fallbacks = {"%n song(s)", f"{count} song(s)"}
    if translated in source_fallbacks:
        return f"{count} song" if count == 1 else f"{count} songs"
    return translated


def render_text(value: str) -> str:
    """Translate only an explicit source template, never arbitrary user text."""

    if not isinstance(value, SourceText):
        return value
    return tr(value.source).format(**dict(value.parameters))
