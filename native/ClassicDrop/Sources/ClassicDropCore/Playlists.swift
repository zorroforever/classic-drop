import Foundation

/// A string-or-integer value. Library identities are always strings, including values in rules.
public enum SmartScalar: Codable, Equatable, Hashable {
    case text(String), integer(Int64)
    public init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if let text = try? value.decode(String.self) { self = .text(text) }
        else { self = .integer(try value.decode(Int64.self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var value = encoder.singleValueContainer()
        switch self { case .text(let text): try value.encode(text); case .integer(let number): try value.encode(number) }
    }
    public var text: String { switch self { case .text(let value): return value; case .integer(let value): return String(value) } }
}
public struct SmartValueDTO: Codable, Equatable, Hashable {
    public var kind: String
    public var value: SmartScalar
    public init(kind: String, value: SmartScalar) { self.kind = kind; self.value = value }
}
/// One recursive syntax tree preserves arbitrary nested all/any groups.
public struct SmartNodeDTO: Codable, Equatable, Hashable {
    public var kind: String
    public var match: String?
    public var rules: [SmartNodeDTO]?
    public var field: String?
    public var `operator`: String?
    public var value: SmartValueDTO?
    public var upperValue: SmartValueDTO?
    public var description: String?
    public init(match: String = "all", rules: [SmartNodeDTO] = []) { kind = "group"; self.match = match; self.rules = rules }
    public init(field: String, operator op: String, value: SmartValueDTO) {
        kind = "rule"; self.field = field; self.operator = op; self.value = value
    }
    enum CodingKeys: String, CodingKey { case kind, match, rules, field, `operator`, value, upperValue, description }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(kind, forKey: .kind)
        switch kind {
        case "group": try c.encode(match ?? "all", forKey: .match); try c.encode(rules ?? [], forKey: .rules)
        case "rule":
            try c.encode(field, forKey: .field); try c.encode(`operator`, forKey: .operator)
            try c.encode(value, forKey: .value); try c.encode(upperValue, forKey: .upperValue)
        default: try c.encode(description, forKey: .description)
        }
    }
}
public struct SmartLimitDTO: Codable, Equatable, Hashable {
    public var value: Int
    public var unit, sort: String
    public var descending: Bool
    public init(value: Int = 50, unit: String = "tracks", sort: String = "random", descending: Bool = false) {
        self.value = value; self.unit = unit; self.sort = sort; self.descending = descending
    }
}
public struct SmartPlaylistDTO: Codable, Equatable, Hashable {
    public var rules: SmartNodeDTO
    public var liveUpdate, matchRules, checkedOnly: Bool
    public var limit: SmartLimitDTO?
    public var editable, supported: Bool
    public var supportReason: String
    public init(rules: SmartNodeDTO = SmartNodeDTO()) {
        self.rules = rules; liveUpdate = true; matchRules = true; checkedOnly = false
        limit = nil; editable = true; supported = true; supportReason = ""
    }
    enum CodingKeys: String, CodingKey { case rules, liveUpdate, matchRules, checkedOnly, limit, editable, supported, supportReason }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(rules, forKey: .rules); try c.encode(liveUpdate, forKey: .liveUpdate)
        try c.encode(matchRules, forKey: .matchRules); try c.encode(checkedOnly, forKey: .checkedOnly)
        try c.encode(limit, forKey: .limit); try c.encode(editable, forKey: .editable)
        try c.encode(supported, forKey: .supported); try c.encode(supportReason, forKey: .supportReason)
    }
}
public struct SmartChoiceDTO: Codable, Hashable, Identifiable { public let value, label: String; public var id: String { value } }
public struct SmartFieldDTO: Codable, Hashable, Identifiable {
    public let field, valueKind: String
    public let operators: [String]
    public let choices: [SmartChoiceDTO]
    public var id: String { field }
    public var defaultRule: SmartNodeDTO {
        SmartNodeDTO(field: field, operator: operators.first ?? "is", value: SmartValueDTO(kind: valueKind,
            value: ["text", "choice", "playlist"].contains(valueKind) ? .text(choices.first?.value ?? "") : .integer(0)))
    }
}
public struct PlaylistSummaryDTO: Decodable, Identifiable, Hashable {
    public let id: String
    public let parentId: String?
    public let kind, name, description: String
    public let path: [String]
    public let sortOrder: Int
    public let sortSupported, editable, protected, dirty, canEditEntries, canEditRules: Bool
    public let entryCount, trackCount, durationMs, missingEntryCount: Int
    public let smart: SmartPlaylistDTO?
    public var symbol: String { kind == "folder" ? "folder" : kind == "smart" ? "line.3.horizontal.decrease.circle" : "music.note.list" }
    public var fullPath: String { path.joined(separator: " / ") }
}
public struct PlaylistTrackDTO: Decodable, Hashable, Identifiable {
    public let id, title, artist, album, albumArtist: String
    public let lengthMs: Int
    public let artworkId: String
}
public struct PlaylistEntryDTO: Decodable, Hashable, Identifiable {
    public let entryId, trackId: String
    public let position: Int?
    public let index: Int
    public let missingReference: Bool
    public let track: PlaylistTrackDTO?
    public var id: String { entryId }
    public var sortTitle: String { track?.title ?? "" }
    public var sortArtist: String { track?.artist ?? "" }
    public var sortAlbum: String { track?.album ?? "" }
    public var sortDuration: Int { track?.lengthMs ?? 0 }
}
public struct PlaylistDraftDTO: Decodable {
    public let revision: String
    public let dirty, canUndo, canRedo, locked: Bool
    public let changedIds, deletedIds: [String]
}
public struct PlaylistEditDTO: Encodable {
    public var action: String
    public var playlistId, name, parentId, kind, description: String?
    public var entryIds, trackIds: [String]?
    public var sortOrder: Int?
    public var smart: SmartPlaylistDTO?
    public var allowRepeat: Bool?
    public init(action: String, playlistId: String? = nil) { self.action = action; self.playlistId = playlistId }
}
public struct ImportDestinationDTO: Codable, Equatable {
    public var playlistIds: [String] = []
    public var newName, parentId: String?
    public var keepEmptyNew = false
    public init() {}
}
public struct ImportReuseDTO: Codable, Equatable { public let token, trackId: String; public init(token: String, trackId: String) { self.token = token; self.trackId = trackId } }
public struct PlaylistChangeDTO: Decodable, Identifiable {
    public let subject, identity, action, name, origin: String
    public let fields: [String]
    public var id: String { subject + ":" + identity + ":" + action }
}
public struct PlaylistReviewDTO: Decodable, Identifiable {
    public let token, operation: String
    public let added, reused, changeCount: Int
    public let noChanges: Bool
    public let changes: [PlaylistChangeDTO]
    public var id: String { token }
    public init(token: String, operation: String, added: Int, reused: Int, changeCount: Int, noChanges: Bool, changes: [PlaylistChangeDTO]) {
        self.token = token; self.operation = operation; self.added = added; self.reused = reused
        self.changeCount = changeCount; self.noChanges = noChanges; self.changes = changes
    }
}
public struct PlaylistIDMapDTO: Decodable { public let draftId, outputId: String }
