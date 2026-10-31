import Foundation

public struct AudioFormatDTO: Decodable, Identifiable, Hashable {
    public let id, codec: String
    public let bitDepth, sampleRateHz: Int?
    public let detail: String
    public init(id: String, codec: String = "", bitDepth: Int? = nil, sampleRateHz: Int? = nil, detail: String = "") {
        self.id = id; self.codec = codec; self.bitDepth = bitDepth
        self.sampleRateHz = sampleRateHz; self.detail = detail
    }
    public var codecText: String { codec.isEmpty ? "—" : codec }
    public var bitDepthText: String { bitDepth.map { "\($0)-bit" } ?? "—" }
    public var sampleRateText: String {
        guard let hz = sampleRateHz else { return "—" }
        return (hz % 1000 == 0 ? String(hz / 1000) : String(format: "%.3f", locale: Locale(identifier: "en_US_POSIX"), Double(hz) / 1000)
            .replacingOccurrences(of: "0+$", with: "", options: .regularExpression)) + " kHz"
    }
}

/// A summary is published only after every album member has been observed.
public func audioFormatSummary(ids: [String], formats: [String: AudioFormatDTO], unknown: String) -> String? {
    guard !ids.isEmpty, ids.allSatisfy({ formats[$0] != nil }) else { return nil }
    let facts = ids.compactMap { formats[$0] }
    func joined(_ values: [String]) -> String { Set(values).sorted().joined(separator: " / ") }
    let codecs = joined(facts.map { $0.codec.isEmpty ? unknown : $0.codec })
    let depths = joined(facts.map(\.bitDepthText))
    let rates = joined(facts.map(\.sampleRateText))
    return [codecs, depths, rates].joined(separator: " · ")
}
