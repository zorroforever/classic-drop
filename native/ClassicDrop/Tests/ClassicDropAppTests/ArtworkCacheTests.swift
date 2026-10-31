import XCTest
import AppKit
@testable import ClassicDrop

final class ArtworkCacheTests: XCTestCase {
    private func thumbnail() throws -> Data {
        let bitmap = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 2, pixelsHigh: 2,
            bitsPerSample: 8, samplesPerPixel: 3, hasAlpha: false, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
        return try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
    }

    func testDiskCacheSurvivesNewInstanceAndSeparatesNamespaces() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let data = try thumbnail()
        let cache = ArtworkDiskCache(root: root)
        await cache.write(data, namespace: "library-a", id: "../cover")
        let restarted = ArtworkDiskCache(root: root)
        let hit = await restarted.read(namespace: "library-a", id: "../cover")
        let miss = await restarted.read(namespace: "library-b", id: "../cover")
        XCTAssertEqual(hit, data)
        XCTAssertNil(miss)
    }

    func testCorruptCacheAndUnwritableRootAreMisses() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let cache = ArtworkDiskCache(root: root)
        await cache.write(try thumbnail(), namespace: "a", id: "1")
        let file = try XCTUnwrap(FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)?
            .allObjects.compactMap { $0 as? URL }.first { $0.pathExtension == "png" })
        try Data("broken".utf8).write(to: file)
        let corrupt = await cache.read(namespace: "a", id: "1")
        XCTAssertNil(corrupt)
        try Data("not a directory".utf8).write(to: file)
        let blocked = ArtworkDiskCache(root: file)
        await blocked.write(try thumbnail(), namespace: "a", id: "1")
        let missing = await blocked.read(namespace: "a", id: "1")
        XCTAssertNil(missing)
    }

    func testDiskBudgetEvictsOldEntriesAndRejectsInvalidWrites() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let data = try thumbnail()
        let cache = ArtworkDiskCache(root: root, budget: data.count)
        await cache.write(data, namespace: "a", id: "1")
        await cache.write(data, namespace: "b", id: "2")
        await cache.write(Data("bad".utf8), namespace: "b", id: "2")
        let old = await cache.read(namespace: "a", id: "1")
        let latest = await cache.read(namespace: "b", id: "2")
        XCTAssertNil(old)
        XCTAssertEqual(latest, data)
    }
}
