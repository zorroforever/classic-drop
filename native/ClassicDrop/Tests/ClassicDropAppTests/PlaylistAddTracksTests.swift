import XCTest
import SwiftUI
import AppKit
import ClassicDropCore
@testable import ClassicDrop

final class PlaylistAddTracksTests: XCTestCase {
    @MainActor func testAddingAcrossSearchesUsesPickOrder() async throws {
        let (model, connection) = try connected()
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 600), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let host = NSHostingView(rootView: PlaylistAddTracks().environmentObject(model).environmentObject(model.strings))
        window.contentView = host; window.orderFront(nil)
        defer { window.contentView = nil; window.close() }
        try await Task.sleep(nanoseconds: 100_000_000)
        let table = try XCTUnwrap(descendants(host).compactMap { $0 as? NSTableView }.first)
        let search = try XCTUnwrap(descendants(host).compactMap { $0 as? NSTextField }.first { $0.isEditable })
        for query in ["Second", "First"] {
            search.stringValue = query
            search.delegate?.controlTextDidChange?(Notification(name: NSControl.textDidChangeNotification, object: search))
            try await Task.sleep(nanoseconds: 100_000_000)
            table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        let enter = try XCTUnwrap(NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: window.windowNumber, context: nil, characters: "\r", charactersIgnoringModifiers: "\r", isARepeat: false, keyCode: 36))
        XCTAssertTrue(host.performKeyEquivalent(with: enter))
        try await Task.sleep(nanoseconds: 100_000_000)
        let edit = try XCTUnwrap(connection.requests.last { $0.command == "playlist_edit" }?.playlistEdit)
        XCTAssertEqual(edit.action, "append")
        XCTAssertEqual(edit.trackIds, ["2", "1"])
    }

    @MainActor func testRemovingHiddenPendingTrackPreservesOthersAndReaddingAppendsIt() async throws {
        let (model, connection) = try connected()
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 940, height: 600), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let host = NSHostingView(rootView: PlaylistAddTracks().environmentObject(model).environmentObject(model.strings))
        window.contentView = host; window.orderFront(nil)
        defer { window.contentView = nil; window.close() }
        try await Task.sleep(nanoseconds: 100_000_000)
        let table = try XCTUnwrap(descendants(host).compactMap { $0 as? NSTableView }.first)
        let search = try XCTUnwrap(descendants(host).compactMap { $0 as? NSTextField }.first { $0.isEditable })
        func filter(_ query: String) {
            search.stringValue = query
            search.delegate?.controlTextDidChange?(Notification(name: NSControl.textDidChangeNotification, object: search))
        }
        for query in ["Second", "First"] {
            filter(query)
            try await Task.sleep(nanoseconds: 100_000_000)
            table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        filter("No matching song")
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(table.numberOfRows, 0)
        let pending = try XCTUnwrap(descendants(host).compactMap { $0 as? NSScrollView }.first {
            !($0.documentView is NSTableView) && descendants($0).contains { $0 is NSButton }
        })
        let removals = descendants(pending).compactMap { $0 as? NSButton }
        XCTAssertEqual(removals.count, 2)
        try XCTUnwrap(removals.first).performClick(nil)
        try await Task.sleep(nanoseconds: 100_000_000)
        filter("")
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(table.selectedRowIndexes, IndexSet(integer: 0))
        XCTAssertFalse(connection.requests.contains { $0.command == "playlist_edit" })
        filter("Second")
        try await Task.sleep(nanoseconds: 100_000_000)
        table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        try await Task.sleep(nanoseconds: 50_000_000)
        let enter = try XCTUnwrap(NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: window.windowNumber, context: nil, characters: "\r", charactersIgnoringModifiers: "\r", isARepeat: false, keyCode: 36))
        XCTAssertTrue(host.performKeyEquivalent(with: enter))
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(connection.requests.last { $0.command == "playlist_edit" }?.playlistEdit?.trackIds, ["1", "2"])
    }

    @MainActor func testSelectingAcrossSearchesRetainsEarlierTracks() async throws {
        let (model, connection) = try connected()
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 940, height: 600), styleMask: [.borderless], backing: .buffered, defer: false)
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
        let enter = try XCTUnwrap(NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: window.windowNumber, context: nil, characters: "\r", charactersIgnoringModifiers: "\r", isARepeat: false, keyCode: 36))
        XCTAssertTrue(host.performKeyEquivalent(with: enter))
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(connection.requests.last { $0.command == "playlist_edit" }?.playlistEdit?.trackIds, ["2", "1"])
        window.contentView = nil
    }

    @MainActor private func descendants(_ view: NSView) -> [NSView] {
        view.subviews.flatMap { [$0] + descendants($0) }
    }

    @MainActor private func connected() throws -> (AppModel, StubConnection) {
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
        return (model, connection)
    }

}
