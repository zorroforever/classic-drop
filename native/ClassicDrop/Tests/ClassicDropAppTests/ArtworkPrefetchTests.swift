import XCTest
import AppKit
import ClassicDropCore
@testable import ClassicDrop

@MainActor
final class ArtworkPrefetchTests: XCTestCase {
    private func waitFor(_ predicate: () -> Bool) async throws {
        for _ in 0..<1000 {
            if predicate() { return }
            try await Task.sleep(nanoseconds: 2_000_000)
        }
        XCTFail("Artwork queue did not reach expected state")
    }

    private func library(ids: [String], cache: any ArtworkCaching) throws -> (AppModel, StubConnection) {
        let connection = StubConnection()
        let model = AppModel(client: connection, artworkCache: cache)
        model.start()
        try connection.reply("hello", artworkCacheKey: "namespace")
        try connection.reply("discover", artworkCacheKey: "namespace")
        try connection.reply("prepare_browser", artworkCacheKey: "namespace")
        try connection.reply("albums", extra: #", "albums":[],"total":0"#, artworkCacheKey: "namespace")
        let rows = ids.enumerated().map { index, id in
            """
            {"id":"\(index)","title":"Track","artist":"A","album":"B","album_artist":"A","album_id":"b","genre":"","year":0,"track_number":1,"disc_number":1,"length_ms":1,"size_bytes":1,"artwork_id":"\(id)","source":""}
            """
        }.joined(separator: ",")
        try connection.reply("tracks", extra: ",\"tracks\":[\(rows)],\"total\":\(ids.count)", artworkCacheKey: "namespace")
        return (model, connection)
    }

    private func thumbnail() throws -> Data {
        let bitmap = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 2, pixelsHigh: 2,
            bitsPerSample: 8, samplesPerPixel: 3, hasAlpha: false, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
        return try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
    }

    func testBackgroundCachesAllDistinctCoversBeyondMemoryLimitAndRestartUsesDisk() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let cache = ArtworkDiskCache(root: root)
        let ids = (1...140).map(String.init)
        let (model, connection) = try library(ids: ids + ["1", "0"], cache: cache)
        let data = try thumbnail()
        for count in 1...140 {
            try await waitFor { connection.requests.filter { $0.command == "artwork" }.count == count }
            try connection.reply("artwork", extra: ",\"image\":\"\(data.base64EncodedString())\"", artworkCacheKey: "namespace")
        }
        // Demand the first cover after prefetching well beyond the decoded cache limit.
        model.artwork("1")
        try await waitFor { model.images["1"] != nil }
        XCTAssertEqual(connection.requests.filter { $0.command == "artwork" }.count, 140)
        XCTAssertLessThanOrEqual(model.images.count, 128)
        let persisted = await cache.read(namespace: "namespace", id: "140")
        XCTAssertEqual(persisted, data)

        let (restarted, newConnection) = try library(ids: ["1"], cache: ArtworkDiskCache(root: root))
        restarted.artwork("1")
        try await waitFor { restarted.images["1"] != nil }
        XCTAssertFalse(newConnection.requests.contains { $0.command == "artwork" })
    }

    func testVisibleDemandWinsAndBackgroundPausesForForegroundWork() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, connection) = try library(ids: ["1", "2", "3"], cache: ArtworkDiskCache(root: root))
        try await waitFor { connection.requests.contains { $0.command == "artwork" } }
        XCTAssertEqual(connection.requests.last { $0.command == "artwork" }?.token, "1")
        model.perform("validate", foreground: true)
        model.artwork("3")
        try connection.reply("artwork", artworkCacheKey: "namespace")
        try await Task.sleep(nanoseconds: 20_000_000)
        XCTAssertEqual(connection.requests.filter { $0.command == "artwork" }.count, 1)
        try connection.reply("validate", artworkCacheKey: "namespace")
        try await waitFor { connection.requests.filter { $0.command == "artwork" }.count >= 2 }
        XCTAssertEqual(connection.requests.filter { $0.command == "artwork" }[1].token, "3")
    }

    func testDeviceChangeDiscardsLateArtworkAndStopsOldQueue() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, connection) = try library(ids: ["1", "2"], cache: ArtworkDiskCache(root: root))
        try await waitFor { connection.requests.contains { $0.command == "artwork" } }
        model.select("other")
        try connection.reply("select", generation: "g2", artworkCacheKey: "other-namespace")
        try connection.reply("artwork", extra: ",\"image\":\"\(try thumbnail().base64EncodedString())\"", artworkCacheKey: "namespace")
        try await Task.sleep(nanoseconds: 20_000_000)
        XCTAssertTrue(model.images.isEmpty)
        XCTAssertEqual(connection.requests.filter { $0.command == "artwork" }.count, 1)
    }

    func testPendingDiskHitOrMissCannotReadOrPublishAfterSwitchOrDisconnect() async throws {
        for disconnect in [false, true] {
            for data: Data? in [nil, try thumbnail()] {
                let cache = SuspendedArtworkCache()
                let (model, connection) = try library(ids: ["1", "2"], cache: cache)
                for _ in 0..<1000 {
                    if await cache.hasPending { break }
                    try await Task.sleep(nanoseconds: 2_000_000)
                }
                let pending = await cache.hasPending
                XCTAssertTrue(pending)
                if disconnect { connection.onExit?(1) }
                else {
                    model.select("other")
                    try connection.reply("select", generation: "g2", artworkCacheKey: "new")
                }
                await cache.resume(with: data)
                try await Task.sleep(nanoseconds: 20_000_000)
                XCTAssertTrue(model.images.isEmpty)
                XCTAssertFalse(connection.requests.contains { $0.command == "artwork" })
            }
        }
    }
}

private actor SuspendedArtworkCache: ArtworkCaching {
    private var continuation: CheckedContinuation<Data?, Never>?
    var hasPending: Bool { continuation != nil }
    func read(namespace: String, id: String) async -> Data? {
        await withCheckedContinuation { continuation = $0 }
    }
    func write(_ data: Data, namespace: String, id: String) {}
    func resume(with data: Data?) {
        continuation?.resume(returning: data); continuation = nil
    }
}
