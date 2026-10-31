import XCTest
import SwiftUI
import AppKit
import ClassicDropCore
@testable import ClassicDrop

final class PlaylistAddTracksTests: XCTestCase {
    @MainActor func testSelectingAcrossSearchesRetainsEarlierTracks() async throws {
        let connection = StubConnection()
        let model = AppModel(client: connection)
        let tracks = #"[{"id":"1","title":"First Song","artist":"Artist","album":"Album","album_artist":"Artist","album_id":"album","genre":"","year":2026,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":"ipod"},{"id":"2","title":"Second Song","artist":"Artist","album":"Album","album_artist":"Artist","album_id":"album","genre":"","year":2026,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":"ipod"}]"#
        model.start()
        try connection.reply("hello", extra: #", "capabilities":["playlists-v1"]"#)
        try connection.reply("discover")
        try connection.reply("prepare_browser")
        try connection.reply("tracks", extra: ",\"tracks\":\(tracks),\"total\":2")
        try connection.reply("albums", extra: #", "albums":[],"total":0"#)
        model.selectedPlaylist = "10"
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 660, height: 530), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let host = NSHostingView(rootView: PlaylistAddTracks().environmentObject(model).environmentObject(model.strings))
        window.contentView = host; window.orderFront(nil)
        defer { window.close() }
        try await Task.sleep(nanoseconds: 100_000_000)
        let table = try XCTUnwrap(descendants(host).compactMap { $0 as? NSTableView }.first)
        let search = try XCTUnwrap(descendants(host).compactMap { $0 as? NSTextField }.first { $0.isEditable })
        func filter(_ value: String) {
            search.stringValue = value
            search.delegate?.controlTextDidChange?(Notification(name: NSControl.textDidChangeNotification, object: search))
        }
        filter("First")
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(table.numberOfRows, 1)
        table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        try await Task.sleep(nanoseconds: 50_000_000)
        filter("Second")
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(table.numberOfRows, 1)
        table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        try await Task.sleep(nanoseconds: 50_000_000)
        filter("")
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(table.numberOfRows, 2)
        XCTAssertEqual(table.selectedRowIndexes, IndexSet([0, 1]))
        filter("First")
        try await Task.sleep(nanoseconds: 100_000_000)
        table.deselectAll(nil)
        try await Task.sleep(nanoseconds: 50_000_000)
        filter("")
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(table.selectedRowIndexes, IndexSet(integer: 1))
        table.selectAll(nil)
        try await Task.sleep(nanoseconds: 50_000_000)
        filter("No matching song")
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(table.numberOfRows, 0)
        filter("")
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(table.selectedRowIndexes, IndexSet([0, 1]))
        XCTAssertFalse(connection.requests.contains { $0.command == "playlist_edit" })
        window.contentView = nil
    }

    @MainActor private func descendants(_ view: NSView) -> [NSView] {
        view.subviews.flatMap { [$0] + descendants($0) }
    }

}
