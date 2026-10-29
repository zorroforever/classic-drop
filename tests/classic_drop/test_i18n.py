from pathlib import Path
from xml.etree import ElementTree

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from classic_drop.engine import PreviewEntry
from classic_drop.i18n import (
    CATALOG_DIRECTORY,
    LanguageManager,
    get_language_manager,
    render_text,
    resolve_language,
    resolve_system_language,
    song_count,
    tr,
)
from classic_drop.window import MainWindow
from classic_drop.worker import Reply
from iOpenPod.app.display_text import source_text
from iOpenPod.app.library_write import WriteProgress


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def languages(app, tmp_path):
    manager = get_language_manager(app, directory=tmp_path)
    manager.set_language("en")
    yield manager
    manager.close()


@pytest.mark.parametrize(
    ("preferences", "expected"),
    [
        (["zh-Hans-CN"], "zh_CN"),
        (["zh_CN"], "zh_CN"),
        (["zh-SG"], "zh_CN"),
        (["ja-JP"], "ja_JP"),
        (["en-GB"], "en"),
        (["zh-TW", "ja-JP"], "ja_JP"),
        (["fr-FR", "zh-Hans"], "zh_CN"),
        (["en-US", "ja-JP"], "en"),
        (["zh-Hant-HK"], "en"),
        (["ru-RU"], "en"),
        ([], "en"),
    ],
)
def test_resolves_supported_system_preferences_in_order(preferences, expected):
    assert expected == resolve_language(preferences)


def test_falls_back_to_macos_language_preferences_when_qt_reports_c():
    assert resolve_system_language(["C"], ["ja-CN", "zh-Hans-CN"]) == "ja_JP"


def test_follow_system_clears_manual_language_override(app, monkeypatch, tmp_path):
    from classic_drop import i18n

    monkeypatch.setattr(
        i18n, "_system_language", lambda: "zh_CN", raising=False
    )
    manager = LanguageManager(app, tmp_path)
    try:
        manager.set_language("ja_JP")
        assert manager.language == "ja_JP"
        manager.set_language("system")
        assert manager.language == "zh_CN"
        assert manager.follows_system
        manager.close()
        restarted = LanguageManager(app, tmp_path)
        try:
            assert restarted.language == "zh_CN"
            assert restarted.follows_system
        finally:
            restarted.close()
    finally:
        manager.close()


def test_system_language_override_is_resolved_again_on_restart(
    app, monkeypatch, tmp_path
):
    from classic_drop import i18n

    current = {"language": "ja_JP"}
    monkeypatch.setattr(
        i18n, "_system_language", lambda: current["language"], raising=False
    )
    manager = LanguageManager(app, tmp_path)
    try:
        assert manager.language == "ja_JP"
        assert manager.follows_system
        current["language"] = "zh_CN"
    finally:
        manager.close()
    restarted = LanguageManager(app, tmp_path)
    try:
        assert restarted.language == "zh_CN"
    finally:
        restarted.close()


def test_language_manager_installs_macos_preferred_catalog_when_qt_reports_c(
    app, monkeypatch, tmp_path
):
    from classic_drop import i18n

    monkeypatch.setattr(i18n.QLocale, "system", lambda: i18n.QLocale("C"))
    monkeypatch.setattr(i18n, "_apple_language_preferences", lambda: ("ja-CN",))
    manager = LanguageManager(app, tmp_path)
    try:
        assert manager.language == "ja_JP"
        assert tr("Add files") == "ファイルを追加"
    finally:
        manager.close()


def test_compiled_catalogs_translate_counts_and_preserve_parameters(languages):
    languages.set_language("zh_CN")
    assert song_count(2) == "2 首"
    assert tr("Add files") == "添加文件"
    languages.set_language("ja_JP")
    assert song_count(2) == "2 曲"
    assert tr("Add files") == "ファイルを追加"
    message = source_text("File not found: {path}", path="/音楽/Blue Train.m4a")
    assert render_text(message) == "ファイルが見つかりません：/音楽/Blue Train.m4a"  # noqa: RUF001
    languages.set_language("en")
    assert song_count(1) == "1 song"
    assert song_count(2) == "2 songs"


def test_user_metadata_is_not_translated(languages):
    languages.set_language("ja_JP")
    message = source_text("File not found: {path}", path="Add files")
    assert render_text(message) == "ファイルが見つかりません：Add files"  # noqa: RUF001
    assert render_text("opaque diagnostic 0x123") == "opaque diagnostic 0x123"


def test_engine_errors_are_templates_not_prelocalized_strings():
    from classic_drop import engine

    source = Path(engine.__file__).read_text(encoding="utf-8")
    assert 'raise ValueError(source_text("Select an iPod Classic first"))' in source
    assert '"File changed; preview it again: {name}", name=item.path.name' in source


def test_language_preference_survives_restart(app, languages, tmp_path):
    languages.set_language("ja_JP")
    languages.close()
    restarted = get_language_manager(app, directory=tmp_path)
    try:
        assert restarted.language == "ja_JP"
        assert tr("Add files") == "ファイルを追加"
    finally:
        restarted.close()


def test_invalid_language_does_not_change_active_translation(languages):
    languages.set_language("zh_CN")
    with pytest.raises(ValueError, match="Unsupported"):
        languages.set_language("xx")
    assert languages.language == "zh_CN"
    assert tr("Add files") == "添加文件"


def test_language_switch_preserves_edits_selection_and_progress(app, languages):
    window = MainWindow(start_worker=False)
    entries = (
        PreviewEntry("one", Path("/音楽/one.m4a"), title="One"),
        PreviewEntry("two", Path("/音楽/two.m4a"), title="Two"),
    )
    window.show_entries(entries)
    window.table.item(0, 1).setText("用户标题")
    window.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    window.table.selectRow(1)
    window.library_search.setText("my search")
    window.set_busy(True)
    window._progress(WriteProgress("inspect", "Inspecting", 2, 5, "one.m4a"))
    before = window.edited_entries()
    requests = []
    window.request.connect(lambda command, payload: requests.append(command))
    try:
        languages.set_language("ja_JP")
        assert window.table.horizontalHeaderItem(1).text() == "タイトル"
        assert before == window.edited_entries()
        assert window.table.currentRow() == 1
        assert window.library_search.text() == "my search"
        assert window.progress.value() == 2
        assert window._busy
        assert "one.m4a" in window.status.text()
        assert "音楽を確認中" in window.status.text()
        assert not requests
        languages.set_language("en")
        assert window.table.horizontalHeaderItem(1).text() == "Title"
        assert "Inspecting music" in window.status.text()
    finally:
        window.set_busy(False)
        window.close()


def test_language_menu_offers_system_and_three_named_languages(app, languages):
    window = MainWindow(start_worker=False)
    try:
        assert window.settings_menu.title() == "Settings"
        assert window.general_menu.title() == "General"
        assert window.language_menu.title() == "Language"
        labels = [action.text() for action in window.language_menu.actions()]
        assert labels == ["Follow system", "English", "简体中文", "日本語"]
        assert window.language_actions["en"].isChecked()
        languages.set_language("system")
        assert window.language_actions["system"].isChecked()
        languages.set_language("ja_JP")
        assert window.language_actions["ja_JP"].isChecked()
        assert window.language_menu.title() == "言語"
        assert window.language_actions["system"].text() == "システムに従う"
    finally:
        window.close()


@pytest.mark.parametrize("language", ["zh_CN", "ja_JP"])
def test_translation_catalogs_are_complete_and_keep_placeholders(language):
    from string import Formatter

    catalog = ElementTree.parse(CATALOG_DIRECTORY / f"classic_drop_{language}.ts")
    assert (CATALOG_DIRECTORY / f"classic_drop_{language}.qm").is_file()
    messages = catalog.findall(".//message")
    assert messages
    sources = [message.findtext("source", "") for message in messages]
    assert len(sources) == len(set(sources))
    for message in messages:
        source = message.findtext("source", "")
        translation = message.find("translation")
        assert translation is not None, source
        assert translation.get("type") != "unfinished", source
        values = translation.findall("numerusform") or [translation]
        fields = {name for _, name, _, _ in Formatter().parse(source) if name}
        for value in values:
            translated = value.text or ""
            assert translated, source
            assert fields == {
                name for _, name, _, _ in Formatter().parse(translated) if name
            }, source
            if message.get("numerus") == "yes":
                assert "%Ln" in translated, source


def test_language_switch_retranslates_connected_device_info(app, languages):
    window = MainWindow(start_worker=False)
    window._active = type(
        "Active",
        (),
        {
            "profile": type(
                "Profile", (), {"display_name": "iPod Classic", "model_number": "A1238"}
            )(),
            "candidate": type("Candidate", (), {"available_bytes": 1024})(),
            "library": type("Library", (), {"tracks": (None, None)})(),
        },
    )()
    window._update_device_info()
    try:
        languages.set_language("ja_JP")
        assert "2 曲" in window.device_info.text()
        assert "空き" in window.device_info.text()
        languages.set_language("en")
        assert "2 songs" in window.device_info.text()
        assert "available" in window.device_info.text()
    finally:
        window.close()


def test_canceled_source_message_does_not_open_error_dialog(app, languages, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    languages.set_language("ja_JP")
    window = MainWindow(start_worker=False)
    dialogs = []
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: dialogs.append(True))
    try:
        window._failed("preview", source_text("Operation canceled"), Reply(None, None, False))
        assert not dialogs
        assert window.status.text() == "操作をキャンセルしました"
    finally:
        window.close()
