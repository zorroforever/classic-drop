import XCTest
@testable import ClassicDrop

final class StringsTests: XCTestCase {
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
}
