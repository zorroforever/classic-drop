import Foundation
import SwiftUI

final class Strings: ObservableObject {
    @Published var language: String {
        didSet { UserDefaults.standard.set(language, forKey: "native.language") }
    }
    init() {
        if let saved = UserDefaults.standard.string(forKey: "native.language") { language = saved; return }
        let directory = ProcessInfo.processInfo.environment["CLASSIC_DROP_DATA_DIRECTORY"]
            ?? NSHomeDirectory() + "/Library/Application Support/Classic Drop"
        let settings = (try? String(contentsOfFile: directory + "/settings.ini", encoding: .utf8)) ?? ""
        let old = settings.components(separatedBy: .newlines).first { $0.hasPrefix("language=") }?.dropFirst(9)
        language = ["zh_CN": "zh-Hans", "ja_JP": "ja", "en": "en"][String(old ?? "")] ?? "system"
    }
    var resolved: String {
        if language != "system" { return language }
        for value in Locale.preferredLanguages {
            if value.hasPrefix("zh") && !value.contains("Hant") && !value.contains("TW") && !value.contains("HK") { return "zh-Hans" }
            if value.hasPrefix("ja") { return "ja" }
            if value.hasPrefix("en") { return "en" }
        }
        return "en"
    }
    func text(_ key: String) -> String {
        let resources = Bundle.main.url(forResource: "ClassicDrop_ClassicDrop", withExtension: "bundle").flatMap(Bundle.init(url:)) ?? Bundle.module
        guard let localization = resources.localizations.first(where: { $0.caseInsensitiveCompare(resolved) == .orderedSame }),
              let path = resources.path(forResource: localization, ofType: "lproj"),
              let bundle = Bundle(path: path) else { return key }
        return bundle.localizedString(forKey: key, value: key, table: nil)
    }
}
