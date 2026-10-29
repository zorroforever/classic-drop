import XCTest
import AppKit
import ClassicDropCore
@testable import ClassicDrop

final class StubConnection: HelperConnection {
    var onEvent: ((Envelope) -> Void)?
    var onExit: ((Int32) -> Void)?
    var running = true
    var requests: [RequestDTO] = []
    func start() throws {}
    func send(_ request: RequestDTO) throws { requests.append(request) }
    func reply(
        _ command: String,
        extra: String = "",
        revision: String = "r",
        generation: String = "g"
    ) throws {
        let request = try XCTUnwrap(requests.last { $0.command == command })
        let json = """
        {"version":1,"id":"\(request.id)","event":"result","generation":"\(generation)","sequence":1,"code":"","detail":"","result":{"state":{"generation":"\(generation)","revision":"\(revision)","active_id":"device","active_name":"Synthetic iPod","available_bytes":100,"total_bytes":200,"track_count":2,"queue_count":1,"package_count":0,"can_restore":false,"writes_allowed":true,"recovery_path":""}\(extra)}}
        """
        onEvent?(try Wire.decoder.decode(Envelope.self, from: Data(json.utf8)))
    }
}

final class ModelTests: XCTestCase {
    @MainActor
    func connected() throws -> (AppModel, StubConnection) {
        let connection = StubConnection()
        let model = AppModel(client: connection)
        model.start()
        try connection.reply("hello")
        try connection.reply("discover")
        return (model, connection)
    }

    @MainActor
    func testEditingIsLockedWhileFlushAndImportRun() throws {
        let (model, connection) = try connected()
        let json = """
        {"token":"p","path":"/Synthetic/one.m4a","title":"Original","artist":"Artist","album":"Album","album_artist":"Artist","track_number":1,"disc_number":1,"selected":true,"status":"new","mode":"copy","length_ms":1000,"size_bytes":100,"detail":"","has_artwork":false}
        """
        model.queue = [try Wire.decoder.decode(PreviewDTO.self, from: Data(json.utf8))]
        model.edit("p") { $0.title = "Reviewed" }
        model.importMusic()
        XCTAssertTrue(model.busy)
        model.edit("p") { $0.title = "Unacknowledged" }
        XCTAssertEqual(model.edits["p"]?.title, "Reviewed")
        try connection.reply("edit", revision: "r2")
        XCTAssertTrue(model.busy)
        XCTAssertEqual(connection.requests.last?.command, "commit")
        XCTAssertEqual(connection.requests.last?.revision, "r2")
    }

    @MainActor
    func testEvictedArtworkCanBeRequestedAgain() throws {
        let (model, connection) = try connected()
        let image = NSImage(size: NSSize(width: 2, height: 2))
        image.lockFocus(); NSColor.blue.setFill(); NSRect(x: 0, y: 0, width: 2, height: 2).fill(); image.unlockFocus()
        let data = try XCTUnwrap(image.tiffRepresentation).base64EncodedString()
        model.artwork("1")
        try connection.reply("artwork", extra: ",\"image\":\"\(data)\"")
        XCTAssertNotNil(model.images["1"])
        model.images.removeAll()
        let before = connection.requests.count
        model.artwork("1")
        XCTAssertEqual(connection.requests.count, before + 1)
    }

    @MainActor
    func testStartupDiscoveryDoesNotLeaveACompletedTaskInTheTaskPanel() throws {
        let (model, _) = try connected()

        XCTAssertNil(model.task)
    }

    @MainActor
    func testDiscoveryGenerationChangeReloadsTheLibrary() throws {
        let (model, connection) = try connected()
        model.albums = [
            try Wire.decoder.decode(
                AlbumDTO.self,
                from: Data(
                    #"{"id":"album","title":"Album","artist":"Artist","year":2020,"track_count":2,"duration_ms":60000,"artwork_id":"0"}"#.utf8
                )
            )
        ]
        let requestCount = connection.requests.count

        model.discover()
        try connection.reply("discover", generation: "g2")

        let refreshedCommands = connection.requests.dropFirst(requestCount + 1).map(\.command)
        XCTAssertEqual(refreshedCommands, ["albums", "tracks", "facets", "filter", "package"])
    }
}
