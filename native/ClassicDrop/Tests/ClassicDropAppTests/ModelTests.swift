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
        generation: String = "g",
        packageCount: Int = 0,
        writesAllowed: Bool = true,
        canKeepContents: Bool = false,
        recoveryPath: String = ""
    ) throws {
        let request = try XCTUnwrap(requests.last { $0.command == command })
        let json = """
        {"version":1,"id":"\(request.id)","event":"result","generation":"\(generation)","sequence":1,"code":"","detail":"","result":{"state":{"generation":"\(generation)","revision":"\(revision)","active_id":"device","active_name":"Synthetic iPod","available_bytes":100,"total_bytes":200,"track_count":2,"queue_count":1,"package_count":\(packageCount),"can_restore":false,"writes_allowed":\(writesAllowed),"can_keep_contents":\(canKeepContents),"recovery_path":"\(recoveryPath)"}\(extra)}}
        """
        onEvent?(try Wire.decoder.decode(Envelope.self, from: Data(json.utf8)))
    }
}

final class ModelTests: XCTestCase {
    @MainActor
    func testKeepingCurrentContentsBindsRecoveryAndPreservesPackageForReview() throws {
        let (model, connection) = try connected()
        model.discover()
        try connection.reply("discover", packageCount: 4, writesAllowed: false,
                             canKeepContents: true, recoveryPath: ".iopenpod-recovery/current/transaction.json")
        XCTAssertFalse(model.canReviewRemoval)

        model.keepCurrentContents(try XCTUnwrap(model.state))

        XCTAssertEqual(connection.requests.last?.command, "keep")
        XCTAssertEqual(connection.requests.last?.token, ".iopenpod-recovery/current/transaction.json")
        let count = connection.requests.count
        try connection.reply("keep", packageCount: 4)
        XCTAssertEqual(connection.requests.count, count)
        XCTAssertEqual(model.state?.packageCount, 4)
        XCTAssertTrue(model.canReviewRemoval)
        XCTAssertNil(model.review)
    }

    @MainActor
    func testKeepConfirmationCannotApplyToAChangedDeviceGeneration() throws {
        let (model, connection) = try connected()
        model.discover()
        try connection.reply("discover", writesAllowed: false, canKeepContents: true,
                             recoveryPath: ".iopenpod-recovery/current/transaction.json")
        let confirmed = try XCTUnwrap(model.state)
        model.discover()
        try connection.reply("discover", generation: "other", writesAllowed: false,
                             canKeepContents: true, recoveryPath: ".iopenpod-recovery/current/transaction.json")
        let count = connection.requests.count

        model.keepCurrentContents(confirmed)

        XCTAssertEqual(connection.requests.count, count)
        XCTAssertFalse(model.state?.writesAllowed ?? true)
    }

    @MainActor
    func connected(prepare: Bool = true) throws -> (AppModel, StubConnection) {
        let connection = StubConnection()
        let model = AppModel(client: connection)
        model.start()
        try connection.reply("hello")
        try connection.reply("discover")
        if prepare {
            try connection.reply("prepare_browser")
            try connection.reply("tracks", extra: #", "tracks":[],"total":0"#)
            try connection.reply("albums", extra: #", "albums":[],"total":0"#)
        }
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
        XCTAssertEqual(refreshedCommands, ["prepare_browser"])
    }
    @MainActor
    func testLibraryPreparationLoadsEveryPageWithoutLoadMore() throws {
        let (model, connection) = try connected(prepare: false)
        model.refresh()
        XCTAssertEqual(connection.requests.last?.command, "prepare_browser")
        try connection.reply("prepare_browser")
        try connection.reply("albums", extra: #", "albums":[],"total":0"#)
        try connection.reply("tracks", extra: #", "tracks":[{"id":"1","title":"First","artist":"A","album":"B","album_artist":"A","album_id":"b","genre":"","year":0,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":""}],"total":2,"offset":0"#)
        XCTAssertTrue(connection.requests.contains { $0.command == "tracks" && $0.offset == 1 })
        try connection.reply("tracks", extra: #", "tracks":[{"id":"2","title":"Second","artist":"A","album":"B","album_artist":"A","album_id":"b","genre":"","year":0,"track_number":2,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":""}],"total":2,"offset":1"#)
        XCTAssertEqual(model.tracks.map(\.id), ["1", "2"])
        XCTAssertFalse(model.browserPreparing)
    }

    @MainActor
    func testOpeningAlbumRetainsSharedSelection() throws {
        let (model, _) = try connected()
        let album = try Wire.decoder.decode(AlbumDTO.self, from: Data(#"{"id":"a","title":"Album","artist":"Artist","year":2020,"track_count":2,"duration_ms":1000,"artwork_id":"0"}"#.utf8))
        model.selectedTracks = ["hidden"]
        model.open(album)
        XCTAssertEqual(model.selectedTracks, ["hidden"])
    }

    @MainActor
    func testArtworkDispatchIsBoundedAndDropsHiddenPendingRequests() throws {
        let (model, connection) = try connected()
        for id in ["1", "2", "3", "4"] { model.artwork(id) }
        XCTAssertEqual(connection.requests.filter { $0.command == "artwork" }.count, 2)
        model.releaseArtwork("3")
        try connection.reply("artwork")
        XCTAssertEqual(connection.requests.last { $0.command == "artwork" }?.token, "4")
    }

    @MainActor
    func testChangingDeviceImmediatelyClearsBrowserAndSelection() throws {
        let (model, _) = try connected()
        model.selectedTracks = ["old"]
        model.select("new-device")
        XCTAssertTrue(model.selectedTracks.isEmpty)
        XCTAssertTrue(model.tracks.isEmpty)
        XCTAssertTrue(model.albums.isEmpty)
    }

    @MainActor
    func testSearchUsesCompleteLocalMetadataAndKeepsHiddenSelection() throws {
        let (model, connection) = try connected(prepare: false)
        try connection.reply("prepare_browser")
        try connection.reply("albums", extra: #", "albums":[],"total":0"#)
        try connection.reply("tracks", extra: #", "tracks":[{"id":"1","title":"First","artist":"A","album":"B","album_artist":"A","album_id":"b","genre":"","year":0,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":"","media_kind":"music","search_text":"hidden composer"},{"id":"2","title":"Second","artist":"A","album":"B","album_artist":"A","album_id":"b","genre":"","year":0,"track_number":2,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":"","media_kind":"podcast","search_text":"hidden show"}],"total":2"#)
        model.selectedTracks = ["1"]
        let count = connection.requests.count
        model.query = "HIDDEN SHOW"
        model.loadTracks()
        XCTAssertEqual(model.tracks.map(\.id), ["2"])
        XCTAssertEqual(connection.requests.count, count)
        model.replaceVisibleSelection(["2"], visible: ["2"])
        XCTAssertEqual(model.selectedTracks, ["1", "2"])
        model.addLibrarySelection()
        XCTAssertEqual(connection.requests.last?.command, "package_add")
        XCTAssertEqual(connection.requests.last?.ids, ["1"])
    }

    @MainActor
    func testRepeatedArtworkDemandDoesNotDuplicatePendingRequests() throws {
        let (model, connection) = try connected()
        for id in ["1", "2", "3", "3"] { model.artwork(id) }
        try connection.reply("artwork")
        try connection.reply("artwork")
        try connection.reply("artwork")
        XCTAssertEqual(connection.requests.filter { $0.command == "artwork" && $0.token == "3" }.count, 1)
    }

    @MainActor
    func testCancelClearsPartialCacheAndIgnoresLatePages() throws {
        let (model, connection) = try connected(prepare: false)
        try connection.reply("prepare_browser")
        model.cancel()
        try connection.reply("tracks", extra: #", "tracks":[],"total":0"#)
        try connection.reply("albums", extra: #", "albums":[],"total":0"#)
        XCTAssertFalse(model.browserPreparing)
        XCTAssertFalse(model.browserReady)
        XCTAssertFalse(model.busy)
        model.refresh()
        XCTAssertEqual(connection.requests.last?.command, "prepare_browser")
    }

    @MainActor
    func testEmptyIncompletePageDoesNotPublishReadyCache() throws {
        let (model, connection) = try connected(prepare: false)
        try connection.reply("prepare_browser")
        try connection.reply("albums", extra: #", "albums":[],"total":0"#)
        try connection.reply("tracks", extra: #", "tracks":[],"total":2"#)
        XCTAssertFalse(model.browserReady)
        XCTAssertFalse(model.browserPreparing)
        XCTAssertFalse(model.busy)
        XCTAssertFalse(model.error.isEmpty)
    }

    @MainActor
    func testSelectedAlbumAddsAllItsMusicDespiteSearchAndOtherTrackSelection() throws {
        let (model, connection) = try connected(prepare: false)
        try connection.reply("prepare_browser")
        try connection.reply("albums", extra: #", "albums":[{"id":"b","title":"Album","artist":"Artist","year":2020,"track_count":3,"duration_ms":3000,"artwork_id":"0"}],"total":1"#)
        try connection.reply("tracks", extra: #", "tracks":[{"id":"1","title":"First","artist":"A","album":"Album","album_artist":"A","album_id":"b","genre":"","year":0,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":"","media_kind":"music"},{"id":"2","title":"Second","artist":"A","album":"Album","album_artist":"A","album_id":"b","genre":"","year":0,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":"","media_kind":"music"},{"id":"3","title":"Episode","artist":"A","album":"Album","album_artist":"A","album_id":"b","genre":"","year":0,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":"","media_kind":"podcast"},{"id":"4","title":"Other","artist":"A","album":"Album","album_artist":"A","album_id":"other","genre":"","year":0,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":"","media_kind":"music"}],"total":4"#)
        let album = try XCTUnwrap(model.albums.first)
        model.selectedTracks = ["4"]
        model.query = "First"
        model.loadTracks()
        model.selectAlbum(album)

        XCTAssertEqual(model.tracks.map(\.id), ["1"])
        XCTAssertEqual(model.selectedTracks, ["1", "2"])
        model.addLibrarySelection()

        XCTAssertEqual(model.selectedMusicCount, 2)
        XCTAssertEqual(connection.requests.last?.command, "package_add")
        XCTAssertEqual(connection.requests.last?.ids, ["1", "2"])
    }

    @MainActor
    func testRemovalReviewRequiresNonemptyPackageAndWriteEligibility() throws {
        let (model, connection) = try connected()
        let before = connection.requests.count

        model.prepareRemoval()
        XCTAssertEqual(connection.requests.count, before)

        model.loadPackage()
        try connection.reply("package", packageCount: 2, writesAllowed: false)
        let readOnlyCount = connection.requests.count
        model.prepareRemoval()
        XCTAssertEqual(connection.requests.count, readOnlyCount)

        model.loadPackage()
        try connection.reply("package", packageCount: 2)
        model.prepareRemoval()
        XCTAssertEqual(connection.requests.last?.command, "prepare_delete")
        XCTAssertFalse(connection.requests.contains { $0.command == "delete" })
    }

}
