from pathlib import Path
from xml.etree import ElementTree

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from classic_drop.engine import PreviewEntry
from classic_drop.i18n import (
    CATALOG_DIRECTORY,
    get_language_manager,
    render_text,
    resolve_language,
    song_count,
    tr,
)
from classic_drop.window import MainWindow
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


def test_compiled_catalogs_translate_counts_and_preserve_parameters(languages):
    languages.set_language("zh_CN")
    assert "2 首" == song_count(2)
    assert "添加文件" == tr("Add files")
    languages.set_language("ja_JP")
    assert "2 曲" == song_count(2)
    assert "ファイルを追加" == tr("Add files")
    message = source_text("File not found: {path}", path="/音楽/Blue Train.m4a")
    assert "ファイルが見つかりません：/音楽/Blue Train.m4a" == render_text(message)
    languages.set_language("en")
    assert "1 song" == song_count(1)
    assert "2 songs" == song_count(2)


def test_user_metadata_is_not_translated(languages):
    languages.set_language("ja_JP")
    message = source_text("File not found: {path}", path="Add files")
    assert "ファイルが見つかりません：Add files" == render_text(message)
    assert "opaque diagnostic 0x123" == render_text("opaque diagnostic 0x123")


def test_language_preference_survives_restart(app, languages, tmp_path):
    languages.set_language("ja_JP")
    languages.close()
    restarted = get_language_manager(app, directory=tmp_path)
    try:
        assert "ja_JP" == restarted.language
        assert "ファイルを追加" == tr("Add files")
    finally:
        restarted.close()


def test_invalid_language_does_not_change_active_translation(languages):
    languages.set_language("zh_CN")
    with pytest.raises(ValueError, match="Unsupported"):
        languages.set_language("xx")
    assert "zh_CN" == languages.language
    assert "添加文件" == tr("Add files")


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
        assert "タイトル" == window.table.horizontalHeaderItem(1).text()
        assert before == window.edited_entries()
        assert 1 == window.table.currentRow()
        assert "my search" == window.library_search.text()
        assert 2 == window.progress.value()
        assert window._busy
        assert "one.m4a" in window.status.text()
        assert "音楽を確認中" in window.status.text()
        assert not requests
        languages.set_language("en")
        assert "Title" == window.table.horizontalHeaderItem(1).text()
        assert "Inspecting music" in window.status.text()
    finally:
        window.set_busy(False)
        window.close()


@pytest.mark.parametrize("language", ["zh_CN", "ja_JP"])
def test_translation_catalogs_are_complete_and_keep_placeholders(language):
    from string import Formatter

    catalog = ElementTree.parse(CATALOG_DIRECTORY / f"classic_drop_{language}.ts")
    assert (CATALOG_DIRECTORY / f"classic_drop_{language}.qm").is_file()
    messages = catalog.findall(".//message")
    assert messages
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
