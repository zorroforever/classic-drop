import XCTest
import SwiftUI
import AppKit
import ClassicDropCore
@testable import ClassicDrop

final class PlaylistModelTests: XCTestCase {
    private let draft = #", "playlist_draft":{"revision":"p1","dirty":true,"can_undo":true,"can_redo":false,"locked":false,"changed_ids":["-1"],"deleted_ids":[]}"#
    private let review = #"{"token":"review","operation":"playlist","added":0,"reused":0,"no_changes":false,"change_count":0,"changes":[]}"#
    private func summary(id: String = "-1", parent: String = "null", path: String = #"["List"]"#, kind: String = "playlist") throws -> PlaylistSummaryDTO {
        try Wire.decoder.decode(PlaylistSummaryDTO.self, from: Data("""
        {"id":"\(id)","parent_id":\(parent),"kind":"\(kind)","name":"List","description":"","path":\(path),"sort_order":1,"sort_supported":true,"editable":true,"protected":false,"dirty":true,"can_edit_entries":true,"can_edit_rules":false,"entry_count":2,"track_count":1,"duration_ms":2000,"missing_entry_count":0,"smart":null}
        """.utf8))
    }
    @MainActor private func connected() throws -> (AppModel, StubConnection) {
        let connection = StubConnection(); let model = AppModel(client: connection)
        model.start(); try connection.reply("hello", extra: #", "capabilities":["playlists-v1"]"#)
        try connection.reply("discover", extra: draft)
        try connection.reply("prepare_browser", extra: draft)
        try connection.reply("tracks", extra: #", "tracks":[],"total":0"#)
        try connection.reply("albums", extra: #", "albums":[],"total":0"#)
        model.playlistItems = [try summary()]; model.selectedPlaylist = "-1"
        return (model, connection)
    }
    @MainActor func testEntryPagingGatesOrderAndRemovalUsesOccurrenceIDs() throws {
        let (model, connection) = try connected()
        model.loadPlaylistEntries()
        XCTAssertFalse(model.canReorderEntries)
        let entry1 = #"{"entry_id":"one","track_id":"9007199254740993","index":0,"position":0,"missing_reference":true,"track":null}"#
        let entry2 = #"{"entry_id":"two","track_id":"9007199254740993","index":1,"position":1,"missing_reference":true,"track":null}"#
        try connection.reply("playlist_entries", extra: draft + ",\"playlist_entries\":[\(entry1)],\"total\":2")
        XCTAssertFalse(model.canReorderEntries)
        XCTAssertEqual(connection.requests.last?.offset, 1)
        try connection.reply("playlist_entries", extra: draft + ",\"playlist_entries\":[\(entry2)],\"total\":2")
        XCTAssertTrue(model.canReorderEntries)
        model.selectedEntries = ["two"]; model.changeEntries("remove_entries")
        XCTAssertEqual(connection.requests.last?.playlistEdit?.entryIds, ["two"])
        XCTAssertNil(connection.requests.last?.playlistEdit?.trackIds)
        XCTAssertEqual(connection.requests.last?.playlistRevision, "p1")
    }
    @MainActor func testDraftChangeInvalidatesReviewAndHelperLossClearsAllIdentity() throws {
        let (model, connection) = try connected()
        model.preparePlaylistReview()
        try connection.reply("playlist_prepare", extra: draft + ",\"playlist_review\":\(review)")
        XCTAssertTrue(model.playlistReviewComplete)
        var edit = PlaylistEditDTO(action: "update", playlistId: "-1"); edit.name = "Renamed"
        model.mutatePlaylist(edit)
        XCTAssertNil(model.playlistReview)
        connection.onExit?(1)
        XCTAssertNil(model.playlistDraft); XCTAssertNil(model.selectedPlaylist)
        XCTAssertFalse(model.playlistEntriesComplete); XCTAssertTrue(model.importDestination.playlistIds.isEmpty)
    }
    @MainActor func testReviewFlushesMetadataBeforePreparingAndNeverImportsDirectly() throws {
        let (model, connection) = try connected()
        let entry = #"{"token":"source","path":"/Synthetic/track.m4a","title":"Original","artist":"A","album":"B","album_artist":"A","track_number":1,"disc_number":1,"selected":true,"status":"new","mode":"copy","length_ms":1000,"size_bytes":100,"detail":"","has_artwork":false}"#
        model.queue = [try Wire.decoder.decode(PreviewDTO.self, from: Data(entry.utf8))]
        model.edit("source") { $0.title = "Reviewed" }
        model.preparePlaylistReview(includeImports: true)
        XCTAssertEqual(connection.requests.last?.command, "edit")
        try connection.reply("edit", extra: draft, revision: "queue-2")
        XCTAssertEqual(connection.requests.last?.command, "playlist_prepare")
        XCTAssertEqual(connection.requests.last?.revision, "queue-2")
        XCTAssertEqual(connection.requests.last?.includeImports, true)
        XCTAssertFalse(connection.requests.contains { $0.command == "commit" })
    }
    @MainActor func testLifecycleWaitsForSaveAndRemapsSelectionAcrossGeneration() throws {
        let (model, connection) = try connected()
        let before = connection.requests.count
        model.eject()
        XCTAssertNotNil(model.pendingLifecycle)
        XCTAssertEqual(connection.requests.count, before)
        model.preparePlaylistReview()
        try connection.reply("playlist_prepare", extra: draft + ",\"playlist_review\":\(review)")
        model.savePlaylistReview()
        XCTAssertEqual(connection.requests.last?.command, "playlist_save")
        try connection.reply("playlist_save", extra: #", "playlist_draft":{"revision":"p2","dirty":false,"can_undo":false,"can_redo":false,"locked":false,"changed_ids":[],"deleted_ids":[]},"playlist_id_map":[{"draft_id":"-1","output_id":"18446744073709551615"}]"#, generation: "g2")
        XCTAssertEqual(model.selectedPlaylist, "18446744073709551615")
        XCTAssertEqual(connection.requests.last?.command, "eject")
    }
    @MainActor func testDeletionScopeUsesIDsDespiteDuplicateFolderNames() throws {
        let (model, _) = try connected()
        let first = try summary(id: "1", path: #"["Folder"]"#, kind: "folder")
        model.playlistItems = [first, try summary(id: "2", path: #"["Folder"]"#, kind: "folder"), try summary(id: "3", parent: #""1""#, path: #"["Folder","List"]"#), try summary(id: "4", parent: #""2""#, path: #"["Folder","List"]"#)]
        XCTAssertEqual(Set(model.playlistDeletionScope(first).map(\.id)), ["1", "3"])
    }
    @MainActor func testLateEntryReplyCannotReplaceAnotherPlaylistAndChangedPageRestarts() throws {
        let (model, connection) = try connected()
        model.loadPlaylistEntries()
        let old = try XCTUnwrap(connection.requests.last { $0.command == "playlist_entries" })
        model.playlistItems.append(try summary(id: "2"))
        model.openPlaylist("2")
        let current = try XCTUnwrap(connection.requests.last { $0.command == "playlist_entries" })
        connection.requests.append(old)
        try connection.reply("playlist_entries", extra: draft + #", "playlist_entries":[],"total":0"#)
        XCTAssertFalse(model.playlistEntriesComplete)
        XCTAssertEqual(model.selectedPlaylist, "2")
        connection.requests.append(current)
        try connection.reply("playlist_entries", extra: draft + #", "playlist_entries":[],"total":0"#)
        XCTAssertTrue(model.playlistEntriesComplete)
    }
    @MainActor func testReviewPagesCarryDraftRevisionAndBlockSaveUntilComplete() throws {
        let (model, connection) = try connected()
        model.preparePlaylistReview()
        let first = #"{"token":"review","operation":"playlist","added":0,"reused":0,"no_changes":false,"change_count":2,"changes":[{"subject":"playlist","identity":"-1","action":"update","name":"List","origin":"draft","fields":["name"]}]}"#
        try connection.reply("playlist_prepare", extra: draft + ",\"playlist_review\":\(first)")
        XCTAssertFalse(model.playlistReviewComplete)
        XCTAssertEqual(connection.requests.last?.command, "playlist_review")
        XCTAssertEqual(connection.requests.last?.playlistRevision, "p1")
        let count = connection.requests.count
        model.savePlaylistReview()
        XCTAssertEqual(connection.requests.count, count)
        try connection.reply("playlist_review", extra: draft + ",\"playlist_review\":\(first)")
        XCTAssertTrue(model.playlistReviewComplete)
        XCTAssertEqual(model.playlistReview?.changes.count, 2)
    }
    @MainActor func testLargeOccurrenceMutationUsesAtomicManifestAndChunks() throws {
        let (model, connection) = try connected()
        var edit = PlaylistEditDTO(action: "remove_entries", playlistId: "-1")
        edit.entryIds = (0..<4001).map { "entry-\($0)" }
        model.mutatePlaylist(edit)
        XCTAssertEqual(connection.requests.last?.command, "playlist_edit_begin")
        XCTAssertEqual(connection.requests.last?.batchCount, 4001)
        XCTAssertNil(connection.requests.last?.playlistEdit?.entryIds)
        try connection.reply("playlist_edit_begin", extra: draft + #", "batch_token":"batch""#)
        for count in [2000, 2000, 1] {
            XCTAssertEqual(connection.requests.last?.ids?.count, count)
            XCTAssertEqual(connection.requests.last?.source, "entries")
            try connection.reply("playlist_edit_chunk", extra: draft)
        }
        XCTAssertEqual(connection.requests.last?.command, "playlist_edit_finish")
        XCTAssertEqual(connection.requests.last?.token, "batch")
    }
    @MainActor func testNativePlaylistViewsRenderWithSyntheticData() throws {
        let (model, _) = try connected()
        let savedLanguage = UserDefaults.standard.object(forKey: "native.language")
        defer {
            if let savedLanguage { UserDefaults.standard.set(savedLanguage, forKey: "native.language") }
            else { UserDefaults.standard.removeObject(forKey: "native.language") }
        }
        model.strings.language = "en"
        model.workspace = .playlist
        let entries = #"[{"entry_id":"one","track_id":"1","index":0,"position":0,"missing_reference":false,"track":{"id":"1","title":"Midnight Walk","artist":"Haru","album":"Small Hours","album_artist":"Haru","length_ms":186000,"artwork_id":"0"}}]"#
        model.playlistEntries = try Wire.decoder.decode([PlaylistEntryDTO].self, from: Data(entries.utf8))
        model.playlistEntriesComplete = true
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 760), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let host = NSHostingView(rootView: WorkspaceView().environmentObject(model).environmentObject(model.strings))
        window.contentView = host; window.orderFront(nil)
        defer { window.close() }
        host.layoutSubtreeIfNeeded()
        let bitmap = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: bitmap)
        let data = try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
        try data.write(to: URL(fileURLWithPath: "/tmp/classic-drop-playlist-native.png"))
        XCTAssertGreaterThan(data.count, 1000)
    }

    @MainActor func testExplicitReuseSelectsDuplicateAfterDestinationAcknowledgement() throws {
        let (model, connection) = try connected()
        let entry = #"{"token":"source","path":"/Synthetic/track.m4a","title":"Existing","artist":"A","album":"B","album_artist":"A","track_number":1,"disc_number":1,"selected":false,"status":"confirmed_duplicate","mode":"copy","length_ms":1000,"size_bytes":100,"detail":"","has_artwork":false}"#
        model.queue = [try Wire.decoder.decode(PreviewDTO.self, from: Data(entry.utf8))]
        model.saveImportDestination(ImportDestinationDTO(), reuse: [ImportReuseDTO(token: "source", trackId: "9007199254740993")])
        XCTAssertNil(model.edits["source"])
        try connection.reply("import_destination", extra: draft + #", "reuse":[{"token":"source","track_id":"9007199254740993"}]"#)
        XCTAssertEqual(model.edits["source"]?.selected, true)
        XCTAssertEqual(model.edits["source"]?.allowDuplicate, false)
        model.saveImportDestination(ImportDestinationDTO(), reuse: [])
        XCTAssertEqual(connection.requests.last?.command, "edit")
        try connection.reply("edit", extra: draft)
        try connection.reply("import_destination", extra: draft + #", "reuse":[]"#)
        XCTAssertEqual(model.edits["source"]?.selected, false)
        model.preparePlaylistReview(includeImports: true)
        XCTAssertEqual(connection.requests.last?.command, "edit")
    }

    @MainActor func testQueueReorderFlushesEditsAndSendsCompleteOrderedTokens() throws {
        let (model, connection) = try connected()
        let entry = #"{"token":"TOKEN","path":"/Synthetic/track.m4a","title":"Track","artist":"A","album":"B","album_artist":"A","track_number":1,"disc_number":1,"selected":true,"status":"new","mode":"copy","length_ms":1000,"size_bytes":100,"detail":"","has_artwork":false}"#
        model.queue = try ["first", "second", "third"].map { try Wire.decoder.decode(PreviewDTO.self, from: Data(entry.replacingOccurrences(of: "TOKEN", with: $0).utf8)) }
        // State queue count must cover the complete source order.
        let stateJSON = #"{"generation":"g","revision":"r","active_id":"device","active_name":"Test","available_bytes":100,"total_bytes":200,"track_count":2,"queue_count":3,"package_count":0,"can_restore":false,"writes_allowed":true,"recovery_path":""}"#
        model.state = try Wire.decoder.decode(StateDTO.self, from: Data(stateJSON.utf8))
        model.selectedQueue = "second"; model.edit("first") { $0.title = "Changed" }
        model.moveQueue(up: true)
        XCTAssertEqual(connection.requests.last?.command, "edit")
        try connection.reply("edit", extra: draft, revision: "after-edit")
        XCTAssertEqual(connection.requests.last?.command, "queue_reorder")
        XCTAssertEqual(connection.requests.last?.ids, ["second", "first", "third"])
        XCTAssertEqual(connection.requests.last?.revision, "after-edit")
    }
    @MainActor func testNoChangeReviewFinishesLifecycleWithoutADeviceSave() throws {
        let (model, connection) = try connected()
        model.eject(); model.preparePlaylistReview()
        let empty = #"{"token":"review","operation":"playlist","added":0,"reused":0,"no_changes":true,"change_count":0,"changes":[]}"#
        try connection.reply("playlist_prepare", extra: draft + ",\"playlist_review\":\(empty)")
        model.finishEmptyPlaylistReview()
        XCTAssertEqual(connection.requests.last?.command, "playlist_discard")
        XCTAssertFalse(connection.requests.contains { $0.command == "playlist_save" })
        try connection.reply("playlist_discard", extra: #", "playlist_draft":{"revision":"p2","dirty":false,"can_undo":false,"can_redo":false,"locked":false,"changed_ids":[],"deleted_ids":[]}"#)
        XCTAssertEqual(connection.requests.last?.command, "eject")
    }

    @MainActor func testTemporaryHeaderSortPreservesOccurrencesAndRequiresExplicitSave() throws {
        let (model, connection) = try connected()
        let json = #"[{"entry_id":"a","track_id":"1","index":0,"position":0,"missing_reference":false,"track":{"id":"1","title":"Zulu","artist":"A","album":"B","album_artist":"A","length_ms":1000,"artwork_id":"0"}},{"entry_id":"b","track_id":"2","index":1,"position":1,"missing_reference":false,"track":{"id":"2","title":"Alpha","artist":"A","album":"B","album_artist":"A","length_ms":1000,"artwork_id":"0"}},{"entry_id":"c","track_id":"1","index":2,"position":2,"missing_reference":false,"track":{"id":"1","title":"Zulu","artist":"A","album":"B","album_artist":"A","length_ms":1000,"artwork_id":"0"}}]"#
        model.playlistEntries = try Wire.decoder.decode([PlaylistEntryDTO].self, from: Data(json.utf8)); model.playlistEntriesComplete = true
        let count = connection.requests.count
        model.playlistSortOrder = [KeyPathComparator(\PlaylistEntryDTO.sortTitle)]
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["b", "a", "c"])
        XCTAssertEqual(model.playlistEntries.map(\.id), ["a", "b", "c"])
        XCTAssertEqual(connection.requests.count, count)
        XCTAssertFalse(model.canReorderEntries)
        model.saveDisplayedPlaylistOrder()
        XCTAssertEqual(connection.requests.last?.playlistEdit?.action, "reorder_entries")
        XCTAssertEqual(connection.requests.last?.playlistEdit?.sortOrder, 1)
        XCTAssertEqual(connection.requests.last?.playlistEdit?.entryIds, ["b", "a", "c"])
    }

    @MainActor func testRepeatedMovesPreviewLocallyAndSaveOneCompleteOrder() throws {
        let (model, connection) = try connected()
        model.playlistEntries = try orderEntries()
        model.playlistEntriesComplete = true
        model.selectedEntries = ["c"]
        let count = connection.requests.count
        model.changeEntries("move_entries_up")
        model.changeEntries("move_entries_up")
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["c", "a", "b"])
        XCTAssertEqual(model.playlistEntries.map(\.id), ["a", "b", "c"])
        XCTAssertEqual(connection.requests.count, count)
        XCTAssertTrue(model.canSaveDisplayedPlaylistOrder)
        model.saveDisplayedPlaylistOrder()
        XCTAssertEqual(connection.requests.count, count + 1)
        XCTAssertEqual(connection.requests.last?.playlistEdit?.action, "reorder_entries")
        XCTAssertEqual(connection.requests.last?.playlistEdit?.entryIds, ["c", "a", "b"])
        XCTAssertEqual(connection.requests.last?.playlistEdit?.sortOrder, 1)
        XCTAssertFalse(connection.requests.contains { $0.command == "playlist_save" })
    }

    @MainActor func testRepeatedDragsPreviewLocallyUntilSave() throws {
        let (model, connection) = try connected()
        model.playlistEntries = try orderEntries()
        model.playlistEntriesComplete = true
        let count = connection.requests.count
        model.reorderEntries(dragged: ["c"], before: "b")
        model.reorderEntries(dragged: ["c"], before: "a")
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["c", "a", "b"])
        XCTAssertEqual(connection.requests.count, count)
        model.saveDisplayedPlaylistOrder()
        XCTAssertEqual(connection.requests.last?.playlistEdit?.entryIds, ["c", "a", "b"])
    }

    @MainActor func testLocalBlockMovesBoundariesAndRestoreNeverContactHelper() throws {
        let (model, connection) = try connected()
        model.playlistEntries = try orderEntries(); model.playlistEntriesComplete = true
        let count = connection.requests.count
        model.selectedEntries = ["b", "c"]; model.changeEntries("move_entries_up")
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["b", "c", "a"])
        model.changeEntries("move_entries_up")
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["b", "c", "a"])
        model.changeEntries("move_entries_down")
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["a", "b", "c"])
        XCTAssertFalse(model.hasLocalPlaylistOrder)
        model.selectedEntries = ["a", "c"]; model.changeEntries("move_entries_up")
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["a", "c", "b"])
        model.restorePlaylistOrder()
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["a", "b", "c"])
        model.changeEntries("move_entries_down")
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["b", "a", "c"])
        model.restorePlaylistOrder()
        XCTAssertFalse(model.canSaveDisplayedPlaylistOrder)
        XCTAssertEqual(connection.requests.count, count)
    }

    @MainActor func testFailedOrderSaveRetainsPreviewForRetryAndSuccessClearsIt() throws {
        let (model, connection) = try connected()
        model.playlistEntries = try orderEntries(); model.playlistEntriesComplete = true
        model.selectedEntries = ["c"]; model.changeEntries("move_entries_up")
        model.saveDisplayedPlaylistOrder()
        let request = try XCTUnwrap(connection.requests.last { $0.command == "playlist_edit" })
        let failed = """
        {"version":1,"id":"\(request.id)","event":"error","generation":"g","sequence":1,"code":"invalid_request","detail":"Try again"}
        """
        connection.onEvent?(try Wire.decoder.decode(Envelope.self, from: Data(failed.utf8)))
        XCTAssertTrue(model.hasLocalPlaylistOrder)
        XCTAssertTrue(model.canSaveDisplayedPlaylistOrder)
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["a", "c", "b"])
        model.saveDisplayedPlaylistOrder()
        XCTAssertEqual(connection.requests.last?.playlistEdit?.entryIds, ["a", "c", "b"])
        try connection.reply("playlist_edit", extra: draft.replacingOccurrences(of: "p1", with: "p2"))
        XCTAssertFalse(model.hasLocalPlaylistOrder)
        try connection.reply("playlist_entries", extra: entryResult(["a", "c", "b"], revision: "p2"))
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["a", "c", "b"])
        XCTAssertFalse(model.canSaveDisplayedPlaylistOrder)
        XCTAssertFalse(connection.requests.contains { $0.command == "playlist_save" })
    }

    @MainActor func testLocalOrdersSurviveNavigationAndMembershipRefresh() throws {
        let (model, connection) = try connected()
        model.playlistItems.append(try summary(id: "2"))
        model.playlistEntries = try orderEntries(); model.playlistEntriesComplete = true
        model.reorderEntries(dragged: ["c"], before: "a")
        model.openPlaylist("2")
        try connection.reply("playlist_entries", extra: entryResult(["d", "e", "f"]))
        model.selectedEntries = ["e"]; model.changeEntries("move_entries_up")
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["e", "d", "f"])
        model.openPlaylist("-1")
        try connection.reply("playlist_entries", extra: entryResult(["a", "b", "c", "new"]))
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["c", "a", "b", "new"])
        model.loadPlaylistEntries()
        try connection.reply("playlist_entries", extra: entryResult(["a", "c", "new"]))
        XCTAssertEqual(model.sortedPlaylistEntries.map(\.id), ["c", "a", "new"])
        model.saveDisplayedPlaylistOrder()
        XCTAssertEqual(connection.requests.last?.playlistEdit?.entryIds, ["c", "a", "new"])
        try connection.reply("playlist_edit", extra: draft.replacingOccurrences(of: "p1", with: "p2"))
        XCTAssertNil(model.playlistOrderDrafts["-1"])
        XCTAssertNotNil(model.playlistOrderDrafts["2"])
    }

    @MainActor func testLocalOrderBlocksReviewAndLifecycleEvenWithCleanHelperDraft() throws {
        let (model, connection) = try connected()
        model.state = try Wire.decoder.decode(StateDTO.self, from: Data(#"{"generation":"g","revision":"r","active_id":"device","active_name":"Test","available_bytes":100,"total_bytes":200,"track_count":2,"queue_count":0,"package_count":1,"can_restore":false,"writes_allowed":true,"recovery_path":""}"#.utf8))
        model.playlistDraft = try Wire.decoder.decode(PlaylistDraftDTO.self, from: Data(#"{"revision":"p1","dirty":false,"can_undo":false,"can_redo":false,"locked":false,"changed_ids":[],"deleted_ids":[]}"#.utf8))
        model.playlistEntries = try orderEntries(); model.playlistEntriesComplete = true
        model.playlistReview = try Wire.decoder.decode(PlaylistReviewDTO.self, from: Data(review.utf8)); model.playlistReviewComplete = true
        model.reorderEntries(dragged: ["c"], before: "a")
        XCTAssertNil(model.playlistReview)
        XCTAssertTrue(model.hasUnsavedPlaylistChanges)
        let count = connection.requests.count
        model.preparePlaylistReview(); model.savePlaylistReview(); model.restore()
        XCTAssertEqual(connection.requests.count, count)
        XCTAssertFalse(model.error.isEmpty)
        model.eject(); XCTAssertNotNil(model.pendingLifecycle); model.cancelLifecycle()
        model.select("other"); XCTAssertNotNil(model.pendingLifecycle); model.cancelLifecycle()
        model.prepareRemoval(); XCTAssertNotNil(model.pendingLifecycle); model.cancelLifecycle()
        model.terminationReply = { _ in }
        model.requestClose(); XCTAssertNotNil(model.pendingLifecycle); model.cancelLifecycle()
        XCTAssertEqual(connection.requests.count, count)
        model.restorePlaylistOrder()
        XCTAssertFalse(model.hasUnsavedPlaylistChanges)
    }

    @MainActor func testDiscardAndHelperLossClearLocalOrderWithoutSaving() throws {
        let (model, connection) = try connected()
        model.playlistEntries = try orderEntries(); model.playlistEntriesComplete = true
        model.reorderEntries(dragged: ["c"], before: "a")
        model.playlistHistory("playlist_discard")
        try connection.reply("playlist_discard", extra: draft.replacingOccurrences(of: "p1", with: "p2"))
        XCTAssertTrue(model.playlistOrderDrafts.isEmpty)
        try connection.reply("playlist_entries", extra: entryResult(["a", "b", "c"], revision: "p2"))
        model.reorderEntries(dragged: ["c"], before: "a")
        connection.onExit?(1)
        XCTAssertTrue(model.playlistOrderDrafts.isEmpty)
        XCTAssertFalse(connection.requests.contains { $0.command == "playlist_save" })
    }

    private func entryResult(_ ids: [String], revision: String = "p1") -> String {
        let rows = ids.enumerated().map { index, id in
            """
            {"entry_id":"\(id)","track_id":"1","index":\(index),"position":\(index),"missing_reference":true,"track":null}
            """
        }.joined(separator: ",")
        return draft.replacingOccurrences(of: "p1", with: revision) + ",\"playlist_entries\":[\(rows)],\"total\":\(ids.count)"
    }

    private func orderEntries() throws -> [PlaylistEntryDTO] {
        let json = #"[{"entry_id":"a","track_id":"1","index":0,"position":0,"missing_reference":false,"track":{"id":"1","title":"First","artist":"A","album":"B","album_artist":"A","length_ms":1000,"artwork_id":"0"}},{"entry_id":"b","track_id":"2","index":1,"position":1,"missing_reference":false,"track":{"id":"2","title":"Middle","artist":"A","album":"B","album_artist":"A","length_ms":1000,"artwork_id":"0"}},{"entry_id":"c","track_id":"1","index":2,"position":2,"missing_reference":false,"track":{"id":"1","title":"Repeated First","artist":"A","album":"B","album_artist":"A","length_ms":1000,"artwork_id":"0"}}]"#
        return try Wire.decoder.decode([PlaylistEntryDTO].self, from: Data(json.utf8))
    }
    @MainActor func testDisconnectAndHelperLossCancelPendingTermination() throws {
        let (model, connection) = try connected()
        var replies: [Bool] = []; model.terminationReply = { replies.append($0) }
        model.requestClose()
        XCTAssertNotNil(model.pendingLifecycle)
        connection.onExit?(1)
        XCTAssertEqual(replies, [false])
        XCTAssertNil(model.pendingLifecycle)
    }

    @MainActor func testSuccessfulSaveWhileQuittingDoesNotCancelTermination() throws {
        let (model, connection) = try connected()
        var replies: [Bool] = []; model.terminationReply = { replies.append($0) }
        model.requestClose(); model.preparePlaylistReview()
        try connection.reply("playlist_prepare", extra: draft + ",\"playlist_review\":\(review)")
        model.savePlaylistReview()
        try connection.reply("playlist_save", extra: #", "playlist_draft":{"revision":"p2","dirty":false,"can_undo":false,"can_redo":false,"locked":false,"changed_ids":[],"deleted_ids":[]}"#, generation: "g2")
        XCTAssertTrue(replies.isEmpty)
        XCTAssertEqual(connection.requests.last?.command, "close")
        connection.running = false; connection.onExit?(0)
        XCTAssertEqual(replies, [true])
    }

    @MainActor func testHostedPlaylistTableSurvivesRemovingRepeatedArtworkOccurrence() async throws {
        let (model, connection) = try connected()
        model.workspace = .playlist
        let first = #"{"entry_id":"first","track_id":"1","index":0,"position":0,"missing_reference":false,"track":{"id":"1","title":"Repeated","artist":"A","album":"B","album_artist":"A","length_ms":1000,"artwork_id":"11"}}"#
        let middle = first.replacingOccurrences(of: "first", with: "middle").replacingOccurrences(of: "Repeated", with: "Middle")
        let last = first.replacingOccurrences(of: "first", with: "last")
        model.playlistEntries = try Wire.decoder.decode([PlaylistEntryDTO].self, from: Data("[\(first),\(middle),\(last)]".utf8))
        model.playlistEntriesComplete = true
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1080, height: 700), styleMask: [.borderless], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = NSHostingView(rootView: PlaylistView().environmentObject(model).environmentObject(model.strings))
        window.orderFront(nil)
        defer { window.close() }
        try await Task.sleep(nanoseconds: 150_000_000)
        model.selectedEntries = ["last"]; model.changeEntries("remove_entries")
        try connection.reply("playlist_edit", extra: draft.replacingOccurrences(of: "p1", with: "p2"))
        try await Task.sleep(nanoseconds: 100_000_000)
        try connection.reply("playlist_entries", extra: draft.replacingOccurrences(of: "p1", with: "p2") + ",\"playlist_entries\":[\(first),\(middle)],\"total\":2")
        try await Task.sleep(nanoseconds: 150_000_000)
        XCTAssertEqual(model.playlistEntries.map(\.id), ["first", "middle"])
        XCTAssertEqual(model.workspace, .playlist)
        XCTAssertTrue(connection.requests.contains { $0.command == "artwork" && $0.token == "11" })
        window.contentView = nil
        try await Task.sleep(nanoseconds: 100_000_000)
    }

    @MainActor func testSmartPreviewCanCancelInSheetAndIgnoresLateResults() throws {
        let (model, connection) = try connected()
        model.previewSmart(SmartPlaylistDTO(), playlistId: nil)
        let request = try XCTUnwrap(connection.requests.last { $0.command == "playlist_preview" })
        XCTAssertTrue(model.smartPreviewRunning)
        model.cancelSmartPreview()
        XCTAssertEqual(connection.requests.last?.command, "cancel")
        XCTAssertEqual(connection.requests.last?.token, request.id)
        XCTAssertTrue(model.cancelRequested)
        try connection.reply("playlist_preview", extra: draft + #", "tracks":[],"total":10"#)
        XCTAssertFalse(model.busy)
        XCTAssertFalse(model.smartPreviewCalculated)
        XCTAssertTrue(model.smartPreview.isEmpty)
        XCTAssertTrue(model.playlistEditable)
    }
    @MainActor func testCorrelatedSmartValidationErrorUnlocksEditor() throws {
        let (model, connection) = try connected()
        model.previewSmart(SmartPlaylistDTO(), playlistId: nil)
        let request = try XCTUnwrap(connection.requests.last { $0.command == "playlist_preview" })
        let json = """
        {"version":1,"id":"\(request.id)","event":"error","generation":"g","sequence":1,"code":"invalid_request","detail":"Rating must be nonnegative"}
        """
        connection.onEvent?(try Wire.decoder.decode(Envelope.self, from: Data(json.utf8)))
        XCTAssertFalse(model.busy)
        XCTAssertFalse(model.smartPreviewRunning)
        XCTAssertTrue(model.playlistEditable)
        XCTAssertEqual(model.error, "Rating must be nonnegative")
    }

}
