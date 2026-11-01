import ClassicDropCore

extension AppModel {
    // Session-only presentation data. Helper draft revisions remain authoritative.
    func invalidatePlaylistEntryCache() {
        playlistEntryEpoch += 1
        playlistEntryCache = [:]; playlistEntryBuffers = [:]; playlistEntryRequests = [:]
        playlistEntryFailed = []
        playlistPrefetchPending = playlistItems.filter { $0.kind != "folder" }.map(\.id)
        playlistEntries = []; playlistEntriesComplete = false
        playlistEntriesLoading = selectedPlaylist != nil && workspace == .playlist
    }

    func publishPlaylistEntries(_ entries: [PlaylistEntryDTO], id: String) {
        guard selectedPlaylist == id else { return }
        reconcilePlaylistOrder(id, entries: entries)
        playlistEntries = entries; playlistEntriesComplete = true; playlistEntriesLoading = false
        selectedEntries.formIntersection(Set(entries.map(\.id)))
    }

    func failPlaylistEntryRead(_ id: String, requestID: String) {
        guard playlistEntryRequests[id] == requestID else { return }
        playlistEntryRequests.removeValue(forKey: id)
        playlistEntryBuffers.removeValue(forKey: id)
        playlistEntryFailed.insert(id)
        if selectedPlaylist == id { playlistEntriesLoading = false }
    }

    func dispatchPlaylistEntryReads() {
        guard ready, connected, playlistSupported, !busy, !closing else { return }
        if let id = selectedPlaylist, activePlaylist?.kind != "folder",
           playlistEntriesLoading, !playlistEntriesComplete, playlistEntryCache[id] == nil, !playlistEntryFailed.contains(id),
           playlistEntryRequests[id] == nil, playlistEntryReadSlots.count < 2 {
            playlistEntriesLoading = true
            readPlaylistEntryPage(id)
        }
        // At most one background page, leaving a slot for newly visible demand.
        guard playlistEntryReadSlots.count < 2,
              !playlistEntryRequests.keys.contains(where: { $0 != selectedPlaylist }),
              let id = playlistPrefetchPending.first(where: {
                  $0 != selectedPlaylist && playlistEntryCache[$0] == nil &&
                  playlistEntryRequests[$0] == nil && !playlistEntryFailed.contains($0)
              }) else { return }
        readPlaylistEntryPage(id)
    }

    private func readPlaylistEntryPage(_ id: String) {
        let epoch = playlistEntryEpoch, revision = playlistDraft?.revision
        let collected = playlistEntryBuffers[id] ?? []
        var requestID = ""
        perform("playlist_entries", configure: {
            $0.token = id; $0.offset = collected.count; $0.limit = 200
            requestID = $0.id
            playlistEntryRequests[id] = $0.id
            playlistEntryReadSlots.insert($0.id)
        }) { result in
            guard epoch == self.playlistEntryEpoch, self.playlistEntryRequests[id] == requestID else { return }
            self.playlistEntryRequests.removeValue(forKey: id)
            guard revision == result.playlistDraft?.revision else {
                self.playlistEntryBuffers.removeValue(forKey: id)
                return
            }
            let rows = result.playlistEntries ?? [], entries = collected + rows
            if entries.count < (result.total ?? entries.count) {
                guard !rows.isEmpty else {
                    self.playlistEntryFailed.insert(id)
                    self.playlistEntryBuffers.removeValue(forKey: id)
                    if self.selectedPlaylist == id { self.playlistEntriesLoading = false }
                    self.error = self.t("playlist.incomplete")
                    return
                }
                self.playlistEntryBuffers[id] = entries
            } else {
                self.playlistEntryBuffers.removeValue(forKey: id)
                self.playlistEntryCache[id] = entries
                self.playlistPrefetchPending.removeAll { $0 == id }
                self.publishPlaylistEntries(entries, id: id)
            }
        }
    }
}
