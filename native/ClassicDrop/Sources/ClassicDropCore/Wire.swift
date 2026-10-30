import Foundation

public enum Wire {
    public static let maximumMessage = 1_048_576
    public static var decoder: JSONDecoder {
        let value = JSONDecoder()
        value.keyDecodingStrategy = .convertFromSnakeCase
        return value
    }
    public static var encoder: JSONEncoder {
        let value = JSONEncoder()
        value.keyEncodingStrategy = .convertToSnakeCase
        return value
    }
}

public struct LineDecoder {
    private var buffer = Data()
    public init() {}
    public mutating func append(_ data: Data) throws -> [Data] {
        buffer.append(data)
        var lines: [Data] = []
        while let end = buffer.firstIndex(of: 10) {
            let line = Data(buffer[..<end])
            guard line.count <= Wire.maximumMessage else { throw WireError.oversized }
            lines.append(line)
            buffer.removeSubrange(...end)
        }
        guard buffer.count <= Wire.maximumMessage else { throw WireError.oversized }
        return lines
    }
}

public enum WireError: Error { case oversized, incompatible, unavailable }

public struct RequestDTO: Encodable {
    public var version = 1
    public var id = UUID().uuidString
    public var command: String
    public var generation = ""
    public var revision: String?
    public var token: String?
    public var paths: [String]?
    public var ids: [String]?
    public var edits: [EditDTO]?
    public var query: String?
    public var album: String?
    public var offset: Int?
    public var limit: Int?
    public var title: String?
    public var artist: String?
    public var albumFilter: String?
    public var genres: [String?]?
    public var years: [Int?]?
    public var playlists: [String]?
    public var source: String?
    public init(_ command: String, generation: String = "") {
        self.command = command
        self.generation = generation
    }
}

public struct EditDTO: Codable {
    public var token, title, artist, album, albumArtist: String
    public var trackNumber, discNumber: Int
    public var selected: Bool
    public var allowDuplicate: Bool
    public init(_ entry: PreviewDTO) {
        token = entry.token; title = entry.title; artist = entry.artist
        album = entry.album; albumArtist = entry.albumArtist
        trackNumber = entry.trackNumber; discNumber = entry.discNumber
        selected = entry.selected; allowDuplicate = false
    }
}

public struct DeviceDTO: Decodable, Identifiable {
    public let id, name, detail: String
    public let selectable: Bool
    public let availableBytes, totalBytes: Int64
}

public struct TrackDTO: Decodable, Identifiable, Hashable {
    public let id, title, artist, album, albumArtist, albumId, genre: String
    public let year, trackNumber, discNumber, lengthMs: Int
    public let sizeBytes: Int64
    public let artworkId, source: String
    public let mediaKind: String?
    public let searchText: String?
    public var searchable: String {
        (searchText ?? [title, artist, album, albumArtist, genre, String(year)].joined(separator: " "))
            .folding(options: [.caseInsensitive], locale: Locale(identifier: "en_US_POSIX"))
    }
    public var duration: String { durationText(lengthMs) }
}

public struct AlbumDTO: Decodable, Identifiable, Hashable {
    public let id, title, artist: String
    public let year, trackCount, durationMs: Int
    public let artworkId: String
    public var duration: String { durationText(durationMs) }
}

public struct PreviewDTO: Decodable, Identifiable {
    public let token, path: String
    public var title, artist, album, albumArtist: String
    public var trackNumber, discNumber: Int
    public var selected: Bool
    public let status, mode: String
    public let lengthMs: Int
    public let sizeBytes: Int64
    public let detail: String
    public let hasArtwork: Bool
    public var id: String { token }
}

public struct StateDTO: Decodable {
    public let generation, revision, activeId, activeName: String
    public let availableBytes, totalBytes: Int64
    public let trackCount, queueCount, packageCount: Int
    public let canRestore, writesAllowed: Bool
    public let recoveryPath: String
    public let canKeepContents: Bool?
}

public struct ReviewDTO: Decodable, Identifiable {
    public let token: String
    public let sizeBytes: Int64
    public let tracks: [TrackDTO]
    public let playlists: [String]
    public let trackCount: Int
    public var id: String { token }
}

public struct FacetDTO: Decodable, Identifiable {
    public let id, name: String
}

public struct ResultDTO: Decodable {
    public let state: StateDTO
    public let devices: [DeviceDTO]?
    public let tracks: [TrackDTO]?
    public let albums: [AlbumDTO]?
    public let preview: [PreviewDTO]?
    public let genres: [String]?
    public let years: [Int]?
    public let playlists: [FacetDTO]?
    public let review: ReviewDTO?
    public let total, offset, count: Int?
    public let image: String?
    public let warnings: [String]?
    public let guiApplication: Bool?
}

public struct ProgressDTO: Decodable {
    public var phase, message, currentItem, unit: String
    public var completed, total: Int?
    public var fraction: Double?
    public var measurement: String
    public init(phase: String, fraction: Double? = nil) {
        self.phase = phase; self.fraction = fraction
        message = ""; currentItem = ""; unit = ""; measurement = "stage"
    }
}

public struct Envelope: Decodable {
    public let version: Int
    public let id, event, generation: String
    public let sequence: Int
    public let result: ResultDTO?
    public let progress: ProgressDTO?
    public let code, detail: String
}

public func durationText(_ milliseconds: Int) -> String {
    let seconds = max(0, milliseconds / 1000)
    return String(format: "%d:%02d", seconds / 60, seconds % 60)
}

public struct TaskState {
    public let id, command: String
    public let started = Date()
    public private(set) var running = true
    public private(set) var progress: ProgressDTO?
    public private(set) var outcome = ""
    public private(set) var detail = ""
    private var sequence = 0
    public init(id: String, command: String) { self.id = id; self.command = command }
    public mutating func receive(id: String, sequence: Int, progress: ProgressDTO) {
        guard id == self.id, running, sequence > self.sequence else { return }
        self.sequence = sequence
        self.progress = progress
    }
    public mutating func finish(code: String, detail: String) {
        running = false; outcome = code; self.detail = detail
    }
}
