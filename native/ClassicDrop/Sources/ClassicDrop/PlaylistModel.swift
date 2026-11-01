import AppKit
import SwiftUI
import ClassicDropCore

struct PlaylistEditorState: Identifiable {
    let id = UUID()
    var playlist: PlaylistSummaryDTO?
    var kind: String
    var parentId: String?
    var moveOnly = false
}
enum PlaylistLifecycle { case select(String), eject, close, removal }

struct PlaylistOrderDraft {
    let originalEntryIDs: [String]
    let orderedEntryIDs: [String]
}

extension AppModel {
    var activePlaylist: PlaylistSummaryDTO? { playlistItems.first { $0.id == selectedPlaylist } }
    var playlistEditable: Bool { writable && playlistDraft?.locked != true }
    var hasUnsavedPlaylistChanges: Bool { playlistDraft?.dirty == true || !playlistOrderDrafts.isEmpty }
    var hasLocalPlaylistOrder: Bool { selectedPlaylist.map { playlistOrderDrafts[$0] != nil } ?? false }
    var smartPreviewRunning: Bool { busy && task?.command == "playlist_preview" }
    func cancelSmartPreview() {
        guard smartPreviewRunning, !cancelRequested else { return }
        smartPreviewEpoch += 1
        smartPreview = []; smartPreviewTotal = 0; smartPreviewCalculated = false
        cancel()
    }
    var canReorderEntries: Bool {
        playlistEditable && playlistEntriesComplete && playlistQuery.isEmpty && playlistSortOrder.isEmpty &&
        activePlaylist?.canEditEntries == true && [0, 1].contains(activePlaylist?.sortOrder ?? -1)
    }
    var sortedPlaylistEntries: [PlaylistEntryDTO] {
        var entries = playlistEntries
        if let id = selectedPlaylist, let draft = playlistOrderDrafts[id], draft.originalEntryIDs == entries.map(\.id) {
            let byID = Dictionary(uniqueKeysWithValues: entries.map { ($0.id, $0) })
            entries = draft.orderedEntryIDs.compactMap { byID[$0] }
        }
        return playlistSortOrder.isEmpty ? entries : entries.sorted(using: playlistSortOrder)
    }
    var canSaveDisplayedPlaylistOrder: Bool {
        playlistEditable && playlistEntriesComplete && playlistQuery.isEmpty &&
        (hasLocalPlaylistOrder || !playlistSortOrder.isEmpty) && activePlaylist?.canEditEntries == true
    }
    func restorePlaylistOrder() {
        guard playlistEditable, let id = selectedPlaylist else { return }
        playlistOrderDrafts.removeValue(forKey: id); playlistSortOrder = []
    }
    private func stagePlaylistOrder(_ order: [String]) {
        guard let id = selectedPlaylist else { return }
        let original = playlistEntries.map(\.id)
        guard order.count == original.count, Set(order) == Set(original) else { return }
        if order == original { playlistOrderDrafts.removeValue(forKey: id) }
        else { playlistOrderDrafts[id] = PlaylistOrderDraft(originalEntryIDs: original, orderedEntryIDs: order) }
        invalidatePlaylistReview()
    }
    // Keep local moves through refreshes and membership edits, using occurrence identities.
    func reconcilePlaylistOrder(_ id: String, entries: [PlaylistEntryDTO]) {
        guard let draft = playlistOrderDrafts[id] else { return }
        let original = entries.map(\.id), available = Set(original)
        let old = Set(draft.orderedEntryIDs)
        let order = draft.orderedEntryIDs.filter { available.contains($0) } + original.filter { !old.contains($0) }
        if order == original { playlistOrderDrafts.removeValue(forKey: id) }
        else { playlistOrderDrafts[id] = PlaylistOrderDraft(originalEntryIDs: original, orderedEntryIDs: order) }
    }
    func saveDisplayedPlaylistOrder() {
        guard canSaveDisplayedPlaylistOrder, let id = selectedPlaylist else { return }
        var edit = PlaylistEditDTO(action: "reorder_entries", playlistId: id)
        edit.entryIds = sortedPlaylistEntries.map(\.id); edit.sortOrder = 1
        mutatePlaylist(edit) {
            self.playlistOrderDrafts.removeValue(forKey: id)
            if self.selectedPlaylist == id { self.playlistSortOrder = [] }
        }
    }
    func acceptPlaylistState(_ result: ResultDTO) {
        if let capabilities = result.capabilities { playlistSupported = capabilities.contains("playlists-v1") }
        if let draft = result.playlistDraft {
            if let old = playlistDraft, old.revision != draft.revision { invalidatePlaylistReview() }
            playlistDraft = draft
        }
        if let destination = result.destination { importDestination = destination }
        if let reuse = result.reuse { importReuse = reuse }
        if let needs = result.queueNeedsPreparation { queueNeedsPreparation = needs }
        if let needs = result.queueRequiresReselection { queueRequiresReselection = needs }
    }
    func resetPlaylists(warn: Bool, preserveTermination: Bool = false) {
        if !preserveTermination, case .close = pendingLifecycle { terminationReply(false) }
        let lost = hasUnsavedPlaylistChanges
        playlistListEpoch += 1; playlistEntryEpoch += 1; smartPreviewEpoch += 1
        playlistItems = []; playlistDraft = nil; playlistEntries = []; playlistEntriesComplete = false
        playlistOrderDrafts = [:]
        selectedPlaylist = nil; selectedEntries = []; playlistSortOrder = []; smartFields = []; smartPreview = []
        playlistEditor = nil; playlistDelete = nil; playlistAddSheet = false; playlistTargetSheet = false; playlistTrackTargets = false
        pendingLifecycle = nil; importDestination = ImportDestinationDTO(); importReuse = []
        queueNeedsPreparation = false; queueRequiresReselection = false; invalidatePlaylistReview()
        if warn && lost { error = t("playlist.disconnected") }
    }
    func invalidatePlaylistReview() { playlistReview = nil; playlistReviewComplete = false }
    func loadPlaylists() {
        guard connected, playlistSupported else { return }
        playlistListEpoch += 1
        let epoch = playlistListEpoch
        var collected: [PlaylistSummaryDTO] = []
        var revision: String?
        func page() {
            perform("playlist_list", configure: { $0.offset = collected.count; $0.limit = 200 }) { result in
                guard epoch == self.playlistListEpoch else { return }
                if let revision, revision != result.playlistDraft?.revision { self.loadPlaylists(); return }
                revision = result.playlistDraft?.revision
                let rows = result.playlistItems ?? []
                collected += rows
                if collected.count < (result.total ?? collected.count) {
                    guard !rows.isEmpty else { self.error = self.t("playlist.incomplete"); return }
                    page(); return
                }
                self.playlistItems = collected
                let ids = Set(collected.map(\.id))
                self.playlistOrderDrafts = self.playlistOrderDrafts.filter { ids.contains($0.key) }
                if let id = self.selectedPlaylist, !collected.contains(where: { $0.id == id }) {
                    self.selectedPlaylist = nil; self.playlistEntries = []; self.selectedEntries = []
                }
            }
        }
        page()
        if smartFields.isEmpty { perform("playlist_fields", completion: { self.smartFields = $0.smartFields ?? [] }) }
    }
    func openPlaylist(_ id: String) {
        selectedPlaylist = id; workspace = .playlist; selectedEntries = []; playlistQuery = ""; playlistSortOrder = []
        loadPlaylistEntries()
    }
    func loadPlaylistEntries() {
        playlistEntryEpoch += 1
        let epoch = playlistEntryEpoch
        guard let id = selectedPlaylist else { return }
        playlistEntries = []; playlistEntriesComplete = false
        var collected: [PlaylistEntryDTO] = []
        var revision: String?
        func page() {
            perform("playlist_entries", configure: { $0.token = id; $0.offset = collected.count; $0.limit = 200 }) { result in
                guard epoch == self.playlistEntryEpoch, self.selectedPlaylist == id else { return }
                if let revision, revision != result.playlistDraft?.revision { self.loadPlaylistEntries(); return }
                revision = result.playlistDraft?.revision
                let rows = result.playlistEntries ?? []
                collected += rows
                if collected.count < (result.total ?? collected.count) {
                    guard !rows.isEmpty else { self.error = self.t("playlist.incomplete"); return }
                    page(); return
                }
                self.reconcilePlaylistOrder(id, entries: collected)
                self.playlistEntries = collected; self.playlistEntriesComplete = true
                self.selectedEntries.formIntersection(Set(collected.map(\.id)))
            }
        }
        page()
    }
    func mutatePlaylist(_ edit: PlaylistEditDTO, then: @escaping () -> Void = {}) {
        guard playlistEditable else { return }
        if edit.action == "update", edit.sortOrder != nil, let id = edit.playlistId, playlistOrderDrafts[id] != nil {
            error = t("playlist.order.save.first"); return
        }
        invalidatePlaylistReview()
        let entries = edit.entryIds ?? [], tracks = edit.trackIds ?? []
        func finished(_ result: ResultDTO) {
            self.loadPlaylists(); if self.selectedPlaylist != nil { self.loadPlaylistEntries() }; then()
        }
        if entries.count + tracks.count <= 2000 {
            perform("playlist_edit", foreground: true, configure: { $0.playlistRevision = self.playlistDraft?.revision; $0.playlistEdit = edit }, completion: finished)
            return
        }
        var header = edit; header.entryIds = nil; header.trackIds = nil
        let revision = playlistDraft?.revision
        perform("playlist_edit_begin", foreground: true, configure: { $0.playlistRevision = revision; $0.playlistEdit = header; $0.batchCount = entries.count + tracks.count }) { result in
            guard let token = result.batchToken else { self.error = self.t("playlist.incomplete"); return }
            let values = entries.isEmpty ? tracks : entries
            @MainActor func chunk(_ offset: Int) {
                if offset == values.count {
                    self.perform("playlist_edit_finish", foreground: true, configure: { $0.playlistRevision = revision; $0.token = token }, completion: finished); return
                }
                let end = min(offset + 2000, values.count)
                self.perform("playlist_edit_chunk", foreground: true, configure: {
                    $0.playlistRevision = revision; $0.token = token; $0.ids = Array(values[offset..<end])
                    $0.source = entries.isEmpty ? "tracks" : "entries"; $0.offset = offset / 2000
                }) { _ in chunk(end) }
            }
            chunk(0)
        }
    }
    func playlistHistory(_ command: String, then: @escaping () -> Void = {}) {
        guard playlistEditable else { return }
        invalidatePlaylistReview()
        perform(command, foreground: true, configure: { $0.playlistRevision = self.playlistDraft?.revision }) { _ in
            if command == "playlist_discard" { self.playlistOrderDrafts = [:] }
            self.loadPlaylists(); self.loadPlaylistEntries(); then()
        }
    }
    func changeEntries(_ action: String) {
        guard let id = selectedPlaylist, activePlaylist?.canEditEntries == true, playlistEntriesComplete, !selectedEntries.isEmpty else { return }
        if ["move_entries_up", "move_entries_down"].contains(action) {
            guard canReorderEntries else { return }
            var order = sortedPlaylistEntries.map(\.id)
            if action == "move_entries_down" { order.reverse() }
            if order.count > 1 {
                for index in 1..<order.count where selectedEntries.contains(order[index]) && !selectedEntries.contains(order[index - 1]) {
                    order.swapAt(index - 1, index)
                }
            }
            if action == "move_entries_down" { order.reverse() }
            stagePlaylistOrder(order); return
        }
        guard action == "remove_entries" else { return }
        var edit = PlaylistEditDTO(action: action, playlistId: id)
        edit.entryIds = playlistEntries.filter { selectedEntries.contains($0.id) }.map(\.id)
        mutatePlaylist(edit)
    }
    func reorderEntries(dragged: [String], before destination: String) {
        guard canReorderEntries, !dragged.contains(destination) else { return }
        let selected = Set(dragged)
        let current = sortedPlaylistEntries.map(\.id)
        guard !selected.isEmpty, selected.isSubset(of: Set(current)) else { return }
        var order = current.filter { !selected.contains($0) }
        guard let index = order.firstIndex(of: destination) else { return }
        order.insert(contentsOf: current.filter { selected.contains($0) }, at: index)
        stagePlaylistOrder(order)
    }
    func previewSmart(_ smart: SmartPlaylistDTO, playlistId: String?) {
        guard !busy else { return }; smartPreviewEpoch += 1
        let epoch = smartPreviewEpoch
        smartPreview = []; smartPreviewTotal = 0; smartPreviewCalculated = false
        func page() {
            perform("playlist_preview", foreground: true, configure: {
                $0.smart = smart; $0.token = playlistId; $0.offset = self.smartPreview.count; $0.limit = 200
                $0.playlistRevision = self.playlistDraft?.revision
            }) { result in
                guard epoch == self.smartPreviewEpoch else { return }
                let rows = result.tracks ?? []; self.smartPreview += rows
                self.smartPreviewCalculated = true
                self.smartPreviewTotal = result.total ?? self.smartPreview.count
                if self.smartPreview.count < self.smartPreviewTotal && !rows.isEmpty { page() }
            }
        }
        page()
    }
    func preparePlaylistReview(includeImports: Bool = false) {
        guard playlistOrderDrafts.isEmpty else { error = t("playlist.order.save.first"); return }
        guard playlistEditable, !includeImports || !queueNeedsPreparation && !queueRequiresReselection else { error = t(queueRequiresReselection ? "playlist.reselect" : "playlist.reprepare"); return }
        saveEdits {
            self.perform("playlist_prepare", foreground: true, configure: {
                $0.playlistRevision = self.playlistDraft?.revision; $0.includeImports = includeImports
            }) { result in
                guard let review = result.playlistReview else { return }
                self.playlistReview = review
                self.loadPlaylistReviewPages(review)
            }
        }
    }
    private func loadPlaylistReviewPages(_ initial: PlaylistReviewDTO) {
        guard let review = playlistReview, review.token == initial.token else { return }
        if review.changes.count >= review.changeCount { playlistReviewComplete = true; return }
        perform("playlist_review", configure: { $0.token = review.token; $0.offset = review.changes.count; $0.limit = 200 }) { result in
            guard self.playlistReview?.token == review.token, let page = result.playlistReview else { return }
            guard !page.changes.isEmpty else { self.error = self.t("playlist.incomplete"); return }
            self.playlistReview = review.appending(page)
            self.loadPlaylistReviewPages(initial)
        }
    }
    func savePlaylistReview() {
        guard writable, playlistOrderDrafts.isEmpty, playlistReviewComplete, let review = playlistReview, !review.noChanges else { return }
        let action = pendingLifecycle
        let selected = selectedPlaylist
        perform("playlist_save", foreground: true, configure: { $0.token = review.token; $0.playlistRevision = self.playlistDraft?.revision }) { result in
            self.invalidatePlaylistReview(); self.review = nil
            if let selected { self.selectedPlaylist = result.playlistIdMap?.first(where: { $0.draftId == selected })?.outputId ?? selected }
            self.clearBrowser()
            if review.operation == "import" { self.queue = []; self.edits = [:] }
            self.pendingLifecycle = nil
            if let action { self.continueLifecycle(action) }
            else {
                if self.queueNeedsPreparation {
                    self.perform("queue", completion: { result in self.loadQueue(first: result.preview ?? [], total: result.total ?? 0) })
                }
                self.loadPlaylists(); self.loadPlaylistEntries(); self.refresh()
            }
        }
    }
    func continueLifecycle(_ action: PlaylistLifecycle) {
        switch action { case .select(let id): select(id); case .eject: eject(); case .close: requestClose(); case .removal: prepareRemoval() }
    }
    func finishEmptyPlaylistReview() {
        guard playlistReview?.noChanges == true, playlistReviewComplete, playlistEditable else { return }
        let action = pendingLifecycle
        playlistHistory("playlist_discard") {
            self.pendingLifecycle = nil
            if let action { self.continueLifecycle(action) }
        }
    }
    func discardForLifecycle() {
        guard let action = pendingLifecycle else { return }
        playlistHistory("playlist_discard") { self.pendingLifecycle = nil; self.continueLifecycle(action) }
    }
    func cancelLifecycle() {
        if case .close = pendingLifecycle { terminationReply(false) }
        pendingLifecycle = nil
    }
    func saveImportDestination(_ destination: ImportDestinationDTO, reuse: [ImportReuseDTO]? = nil) {
        guard playlistEditable else { return }
        let previousReuse = importReuse
        invalidatePlaylistReview()
        saveEdits {
            self.perform("import_destination", foreground: true, configure: {
                $0.destination = destination; $0.reuse = reuse ?? self.importReuse; $0.playlistRevision = self.playlistDraft?.revision
                $0.allowDuplicates = self.edits.values.filter(\.allowDuplicate).map(\.token)
            }) { _ in
                if let reuse {
                    let selected = Set(reuse.map(\.token))
                    for item in previousReuse where !selected.contains(item.token) {
                        self.edit(item.token) { if !$0.allowDuplicate { $0.selected = false } }
                    }
                    for item in reuse { self.edit(item.token) { $0.selected = true } }
                }
            }
        }
    }
    func reprepareQueue() {
        guard playlistEditable, queueNeedsPreparation else { return }
        perform("queue_reprepare", foreground: true, configure: { $0.playlistRevision = self.playlistDraft?.revision }) { result in
            self.edits = [:]; self.loadQueue(first: result.preview ?? [], total: result.total ?? 0)
        }
    }
    func playlistDeletionScope(_ playlist: PlaylistSummaryDTO) -> [PlaylistSummaryDTO] {
        var ids: Set<String> = [playlist.id]
        var changed = true
        while changed {
            let count = ids.count
            for item in playlistItems { if let parent = item.parentId, ids.contains(parent) { ids.insert(item.id) } }
            changed = ids.count != count
        }
        return playlistItems.filter { ids.contains($0.id) }
    }
}

extension PlaylistReviewDTO {
    func appending(_ page: PlaylistReviewDTO) -> PlaylistReviewDTO {
        // Re-decode the exact typed review with additional pages, keeping its immutable token.
        PlaylistReviewDTO(token: token, operation: operation, added: added, reused: reused,
                          changeCount: changeCount, noChanges: noChanges, changes: changes + page.changes)
    }
}
