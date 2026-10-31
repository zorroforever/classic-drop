import XCTest
import SwiftUI
import AppKit
import ClassicDropCore
@testable import ClassicDrop

final class PlaylistAddTracksTests: XCTestCase {
    @MainActor func testClickingAnotherMatchKeepsBothPendingAndSubmitsBoth() async throws {
        let picker = try await PlaylistPickerHarness()
        defer { picker.close() }
        try await picker.filter("Song")
        XCTAssertEqual(picker.table.numberOfRows, 2)
        try await picker.clickSong(0)
        try await picker.clickSong(1)
        XCTAssertEqual(try picker.pendingButtons().count, 2)
        XCTAssertFalse(picker.connection.requests.contains { $0.command == "playlist_edit" })
        let submitted = try await picker.submit()
        XCTAssertEqual(submitted, ["1", "2"])
    }

    @MainActor func testAddingAcrossSearchesUsesPickOrder() async throws {
        let picker = try await PlaylistPickerHarness()
        defer { picker.close() }
        try await picker.filter("Second")
        try await picker.clickSong(0)
        try await picker.filter("First")
        try await picker.clickSong(0)
        let submitted = try await picker.submit()
        XCTAssertEqual(submitted, ["2", "1"])
    }

    @MainActor func testRemovingHiddenPendingTrackPreservesOthersAndReaddingAppendsIt() async throws {
        let picker = try await PlaylistPickerHarness()
        defer { picker.close() }
        try await picker.filter("Second")
        try await picker.clickSong(0)
        try await picker.filter("First")
        try await picker.clickSong(0)
        try await picker.filter("No matching song")
        XCTAssertEqual(picker.table.numberOfRows, 0)
        try XCTUnwrap(picker.pendingButtons().first).performClick(nil)
        try await Task.sleep(nanoseconds: 100_000_000)
        try await picker.filter("Second")
        try await picker.clickSong(0)
        let submitted = try await picker.submit()
        XCTAssertEqual(submitted, ["1", "2"])
    }

    @MainActor func testSelectingAcrossSearchesRetainsEarlierTracks() async throws {
        let picker = try await PlaylistPickerHarness()
        defer { picker.close() }
        try await picker.filter("First")
        try await picker.clickSong(0)
        try await picker.filter("Second")
        try await picker.clickSong(0)
        try await picker.filter("First")
        try await picker.togglePick(0)
        try await picker.filter("")
        try await picker.selectAllResults()
        try await picker.filter("No matching song")
        try await picker.filter("")
        XCTAssertFalse(picker.connection.requests.contains { $0.command == "playlist_edit" })
        let submitted = try await picker.submit()
        XCTAssertEqual(submitted, ["2", "1"])
    }

    @MainActor func testUncheckingAndRecheckingMatchDoesNotLoseEitherPickAtSubmit() async throws {
        let picker = try await PlaylistPickerHarness()
        defer { picker.close() }
        try await picker.filter("Song")
        try await picker.clickSong(0)
        try await picker.clickSong(1)
        try await picker.togglePick(0)
        try await picker.togglePick(0)
        // Native focus/selection changes must not replace the pending queue.
        picker.table.selectRowIndexes(IndexSet(integer: 0), byExtendingSelection: false)
        picker.table.selectRowIndexes(IndexSet(integer: 1), byExtendingSelection: false)
        try await Task.sleep(nanoseconds: 100_000_000)
        let submitted = try await picker.submit()
        XCTAssertEqual(submitted, ["2", "1"])
    }

    @MainActor func testSelectAllResultsAndRepeatedClickDoNotDuplicatePicks() async throws {
        let picker = try await PlaylistPickerHarness()
        defer { picker.close() }
        try await picker.selectAllResults()
        try await picker.clickSong(1)
        try await picker.selectAllResults()
        let submitted = try await picker.submit()
        XCTAssertEqual(submitted, ["1", "2"])
    }
}

@MainActor private final class PlaylistPickerHarness {
    let connection: StubConnection
    let model: AppModel
    let window: NSWindow
    let host: NSView
    let table: NSTableView
    let search: NSTextField

    init() async throws {
        connection = StubConnection()
        model = AppModel(client: connection)
        let tracks = #"[{"id":"1","title":"First Song","artist":"Artist","album":"Album","album_artist":"Artist","album_id":"album","genre":"","year":2026,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":"ipod"},{"id":"2","title":"Second Song","artist":"Artist","album":"Album","album_artist":"Artist","album_id":"album","genre":"","year":2026,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"0","source":"ipod"}]"#
        model.start()
        try connection.reply("hello", extra: #", "capabilities":["playlists-v1"]"#)
        try connection.reply("discover")
        try connection.reply("prepare_browser")
        try connection.reply("tracks", extra: ",\"tracks\":\(tracks),\"total\":2")
        try connection.reply("albums", extra: #", "albums":[],"total":0"#)
        model.selectedPlaylist = "10"
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 940, height: 600), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        host = NSHostingView(rootView: PlaylistAddTracks().environmentObject(model).environmentObject(model.strings))
        window.contentView = host
        window.orderFront(nil)
        try await Task.sleep(nanoseconds: 100_000_000)
        table = try XCTUnwrap(pickerDescendants(host).compactMap { $0 as? NSTableView }.first)
        search = try XCTUnwrap(pickerDescendants(host).compactMap { $0 as? NSTextField }.first { $0.isEditable })
    }

    func close() {
        window.contentView = nil
        window.close()
    }

    func filter(_ query: String) async throws {
        search.stringValue = query
        search.delegate?.controlTextDidChange?(Notification(name: NSControl.textDidChangeNotification, object: search))
        try await Task.sleep(nanoseconds: 100_000_000)
    }

    func clickSong(_ row: Int) async throws {
        try cellButton(column: 1, row: row).performClick(nil)
        try await Task.sleep(nanoseconds: 100_000_000)
    }

    func togglePick(_ row: Int) async throws {
        try cellButton(column: 0, row: row).performClick(nil)
        try await Task.sleep(nanoseconds: 100_000_000)
    }

    func selectAllResults() async throws {
        let button = try XCTUnwrap(pickerDescendants(host).compactMap { $0 as? NSButton }.first { !$0.isDescendant(of: table) })
        button.performClick(nil)
        try await Task.sleep(nanoseconds: 100_000_000)
    }

    func pendingButtons() throws -> [NSButton] {
        let pending = try XCTUnwrap(pickerDescendants(host).compactMap { $0 as? NSScrollView }.first {
            !($0.documentView is NSTableView) && pickerDescendants($0).contains { $0 is NSButton }
        })
        return pickerDescendants(pending).compactMap { $0 as? NSButton }
    }

    func submit() async throws -> [String] {
        let enter = try XCTUnwrap(NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: window.windowNumber, context: nil, characters: "\r", charactersIgnoringModifiers: "\r", isARepeat: false, keyCode: 36))
        XCTAssertTrue(host.performKeyEquivalent(with: enter))
        try await Task.sleep(nanoseconds: 100_000_000)
        let request = try XCTUnwrap(connection.requests.last { $0.command == "playlist_edit" })
        XCTAssertEqual(request.playlistEdit?.action, "append")
        return try XCTUnwrap(request.playlistEdit?.trackIds)
    }

    private func cellButton(column: Int, row: Int) throws -> NSButton {
        let cell = try XCTUnwrap(table.view(atColumn: column, row: row, makeIfNecessary: true))
        return try XCTUnwrap(pickerDescendants(cell).compactMap { $0 as? NSButton }.first)
    }
}

@MainActor private func pickerDescendants(_ view: NSView) -> [NSView] {
    view.subviews.flatMap { [$0] + pickerDescendants($0) }
}
