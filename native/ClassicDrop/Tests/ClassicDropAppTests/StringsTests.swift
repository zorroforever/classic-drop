import XCTest
import ClassicDropCore
@testable import ClassicDrop

final class StringsTests: XCTestCase {
    func testProgressPresentationRetranslatesWithoutChangingMeasurementsOrUserData() {
        let saved = UserDefaults.standard.object(forKey: "native.language")
        defer {
            if let saved { UserDefaults.standard.set(saved, forKey: "native.language") }
            else { UserDefaults.standard.removeObject(forKey: "native.language") }
        }
        let strings = Strings()
        var progress = ProgressDTO(phase: "database.validation", fraction: 0.25)
        progress.message = "Validating Library changes"
        progress.currentItem = progress.message
        progress.unit = "steps"
        progress.completed = 1; progress.total = 4
        for (language, expected) in [("zh-Hans", "正在验证曲库变更"), ("ja", "ライブラリの変更を検証中"), ("en", "Validating Library changes")] {
            strings.language = language
            let presentation = TaskProgressText(progress, strings: strings)
            XCTAssertEqual(presentation.title, expected)
            XCTAssertEqual(presentation.item, expected)
            XCTAssertEqual(presentation.details, expected + "\n1 / 4")
        }
        strings.language = "zh-Hans"
        progress.phase = "media.reading"
        progress.message = "Reading audio"
        progress.currentItem = "/Music/Validating Library changes.m4a"
        progress.unit = "files"
        let presentation = TaskProgressText(progress, strings: strings)
        XCTAssertEqual(presentation.title, "正在读取音频")
        XCTAssertEqual(presentation.item, "/Music/Validating Library changes.m4a")
        XCTAssertEqual(presentation.details, "正在读取音频\n/Music/Validating Library changes.m4a\n1 / 4")
        XCTAssertEqual(progress.fraction, 0.25)
        XCTAssertEqual(progress.message, "Reading audio")
        progress.phase = "future.phase"
        XCTAssertEqual(TaskProgressText(progress, strings: strings).title, "正在准备…")
    }

    func testEveryLibraryProgressStageHasPackagedTranslations() {
        let saved = UserDefaults.standard.object(forKey: "native.language")
        defer {
            if let saved { UserDefaults.standard.set(saved, forKey: "native.language") }
            else { UserDefaults.standard.removeObject(forKey: "native.language") }
        }
        var phases = [
            "scan", "inspect", "history", "delete.review", "source.verify",
            "media.reading", "media.inspecting", "media.converting", "media.metadata", "media.verifying",
            "browser.index", "browser.loading",
            "source.check", "source.sidecars", "source.recheck", "draft.analysis",
            "draft.smart_playlists", "resources.capture", "save.source_check",
            "save.storage_transaction", "save.cleanup", "save.media_deletion",
            "save.recovery.restoring", "save.recovery.cleanup"
        ]
        phases += ["validation", "resources", "reconciliation", "artwork", "serialization", "signing", "verification"].map { "database." + $0 }
        phases += ["staging", "prepared", "publishing", "committed", "restoring", "restored"].map { "save.storage." + $0 }
        phases += ["save.storage.", "save.recovery."].flatMap { prefix in
              ["verifying_staged", "verifying_writes", "verifying_recovery", "checking_dependencies", "inspecting", "rechecking", "flushing"].map { prefix + $0 }
          }
        phases += ["queue_reorder", "package_add", "playlist_edit", "playlist_edit_begin", "playlist_edit_chunk", "playlist_edit_finish", "playlist_undo", "playlist_redo", "playlist_discard", "playlist_preview", "playlist_prepare", "playlist_save", "import_destination", "queue_reprepare"].map { "operation." + $0 }
        let strings = Strings()
        for language in ["en", "zh-Hans", "ja"] {
            strings.language = language
            for phase in phases {
                XCTAssertNotEqual(strings.text(phase), phase, language + ": " + phase)
            }
        }
    }

    func testSwitchingLanguagesLoadsPackagedTranslations() {
        let defaults = UserDefaults.standard
        let saved = defaults.object(forKey: "native.language")
        defer {
            if let saved { defaults.set(saved, forKey: "native.language") }
            else { defaults.removeObject(forKey: "native.language") }
        }
        let strings = Strings()
        for (language, label) in [("en", "iPod Library"), ("ja", "iPod ライブラリ"), ("zh-Hans", "iPod 曲库")] {
            strings.language = language
            XCTAssertEqual(strings.text("library"), label, language)
            for key in ["playlist", "playlist.move", "playlist.check.combined", "playlist.rules.apply", "playlist.operator.between", "playlist.field.rating", "playlist.import.destination", "playlist.reselect", "playlist.pick", "playlist.pick_all", "playlist.pending.count", "playlist.pending.hint", "playlist.pending.empty", "playlist.pending.remove"] {
                XCTAssertNotEqual(strings.text(key), key, language + ": " + key)
            }
        }
        XCTAssertEqual(strings.text("unknown.test.key"), "unknown.test.key")
    }

    func testPlaylistOrderTranslationsArePackaged() {
        let saved = UserDefaults.standard.object(forKey: "native.language")
        defer {
            if let saved { UserDefaults.standard.set(saved, forKey: "native.language") }
            else { UserDefaults.standard.removeObject(forKey: "native.language") }
        }
        let strings = Strings()
        for language in ["en", "ja", "zh-Hans"] {
            strings.language = language
            for key in ["playlist.order.save", "playlist.order.restore", "playlist.order.pending", "playlist.order.save.first", "playlist.order.lifecycle"] {
                XCTAssertNotEqual(strings.text(key), key, language + ": " + key)
            }
        }
    }
}
