import SwiftUI
import ClassicDropCore
import UniformTypeIdentifiers

struct PlaylistTree: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    var parent: String? = nil
    var ancestors = Set<String>()
    var body: some View {
        ForEach(model.playlistItems.filter { $0.parentId == parent && !ancestors.contains($0.id) }) { item in
            if item.kind == "folder" {
                DisclosureGroup {
                    PlaylistTree(parent: item.id, ancestors: ancestors.union([item.id]))
                } label: { row(item) }
            } else { row(item) }
        }
    }
    private func row(_ item: PlaylistSummaryDTO) -> some View {
        Button { model.openPlaylist(item.id) } label: {
            HStack {
                Label(item.name, systemImage: item.symbol).lineLimit(1)
                Spacer(minLength: 0)
                if item.dirty { Image(systemName: "circle.fill").font(.system(size: 5)).accessibilityLabel(strings.text("playlist.unsaved")) }
            }.contentShape(Rectangle())
                .foregroundStyle(model.selectedPlaylist == item.id && model.workspace == .playlist ? Color.accentColor : Color.primary)
        }.buttonStyle(.plain).help(item.fullPath)
        .contextMenu {
            Button(strings.text("playlist.edit")) { model.playlistEditor = PlaylistEditorState(playlist: item, kind: item.kind, parentId: item.parentId) }.disabled(!item.editable || !model.playlistEditable)
            Button(strings.text("playlist.move")) { model.playlistEditor = PlaylistEditorState(playlist: item, kind: item.kind, parentId: item.parentId, moveOnly: true) }.disabled(!item.editable || !model.playlistEditable)
            Button(strings.text("playlist.delete")) { model.playlistDelete = item }.disabled(!item.editable || !model.playlistEditable)
        }
        .onDrag { NSItemProvider(object: ("playlist:" + item.id) as NSString) }
        .onDrop(of: [UTType.text], isTargeted: nil) { providers in
            guard (item.kind == "folder" || item.canEditEntries), model.playlistEditable, let provider = providers.first else { return false }
            _ = provider.loadObject(ofClass: NSString.self) { value, _ in
                guard let text = value as? String else { return }
                Task { @MainActor in
                    if text.hasPrefix("playlist:"), item.kind == "folder" {
                        var edit = PlaylistEditDTO(action: "move", playlistId: String(text.dropFirst(9))); edit.parentId = item.id
                        model.mutatePlaylist(edit)
                    } else if text.hasPrefix("tracks:"), item.canEditEntries {
                        var edit = PlaylistEditDTO(action: "append", playlistId: item.id)
                        edit.trackIds = text.dropFirst(7).split(separator: ",").map(String.init)
                        model.mutatePlaylist(edit)
                    }
                }
            }; return true
        }
    }
}

struct PlaylistView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    private func t(_ key: String) -> String { strings.text(key) }
    private var visible: [PlaylistEntryDTO] {
        model.sortedPlaylistEntries.filter { entry in
            model.playlistQuery.isEmpty || [entry.track?.title ?? "", entry.track?.artist ?? "", entry.track?.album ?? ""].joined(separator: " ").localizedCaseInsensitiveContains(model.playlistQuery)
        }
    }
    var body: some View {
        if let item = model.activePlaylist {
            VStack(spacing: 0) {
                header(item)
                Divider()
                if item.kind == "folder" { folder(item) }
                else { entries(item) }
            }
        } else {
            EmptyWorkspace(symbol: "music.note.list", title: t("playlist.none"), detail: t("playlist.none.hint")) {
                Button(t("playlist.new")) { model.playlistEditor = PlaylistEditorState(kind: "playlist") }.disabled(!model.playlistEditable)
            }
        }
    }
    private func header(_ item: PlaylistSummaryDTO) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label(item.name, systemImage: item.symbol).font(.title2.bold())
                Spacer()
                GlassControls {
                    HStack {
                        if item.canEditEntries {
                            Button(t("playlist.add")) { model.playlistAddSheet = true }
                        }
                        if item.canEditRules && item.smart?.editable != false {
                            Button(t("playlist.rules.edit")) { model.playlistEditor = PlaylistEditorState(playlist: item, kind: item.kind, parentId: item.parentId) }
                            Button(t("playlist.evaluate")) { model.mutatePlaylist(PlaylistEditDTO(action: "evaluate", playlistId: item.id)) }
                        }
                        Menu {
                            Button(t("playlist.edit")) { model.playlistEditor = PlaylistEditorState(playlist: item, kind: item.kind, parentId: item.parentId) }.disabled(!item.editable)
                            Button(t("playlist.move")) { model.playlistEditor = PlaylistEditorState(playlist: item, kind: item.kind, parentId: item.parentId, moveOnly: true) }.disabled(!item.editable)
                            if item.kind == "smart" {
                                Button(t("playlist.copy")) {
                                    var edit = PlaylistEditDTO(action: "copy_regular", playlistId: item.id)
                                    edit.name = item.name + " " + t("playlist.copy.suffix"); edit.parentId = item.parentId
                                    model.mutatePlaylist(edit)
                                }
                            }
                            if item.canEditEntries {
                                Button(t("playlist.import.here")) {
                                    model.addFiles(folder: false, playlistId: item.id)
                                }
                            }
                            Divider()
                            Button(t("playlist.delete")) { model.playlistDelete = item }.disabled(!item.editable)
                        } label: { Image(systemName: "ellipsis") }
                    }.disabled(!model.playlistEditable)
                }
            }
            Text(item.fullPath).font(.caption).foregroundStyle(.secondary)
            Text(String(format: t("playlist.summary"), item.entryCount, durationText(item.durationMs))).font(.callout).foregroundStyle(.secondary)
            if let smart = item.smart {
                Text(t(smart.liveUpdate ? "playlist.live.on" : "playlist.live.off")).font(.caption)
                if !smart.supported || !smart.editable {
                    Label(t("playlist.unsupported"), systemImage: "lock").foregroundStyle(.orange)
                    Text(smart.supportReason).font(.caption).textSelection(.enabled)
                }
            }
            if item.protected { Label(t("playlist.protected"), systemImage: "lock").font(.caption) }
        }.padding(18)
    }
    private func folder(_ item: PlaylistSummaryDTO) -> some View {
        List(model.playlistItems.filter { $0.parentId == item.id }) { child in
            Button { model.openPlaylist(child.id) } label: {
                HStack { Label(child.name, systemImage: child.symbol); Spacer(); Text("\(child.entryCount)").foregroundStyle(.secondary) }
            }.buttonStyle(.plain)
        }.overlay(alignment: .bottomTrailing) {
            Menu(t("playlist.new")) {
                ForEach(["playlist", "smart", "folder"], id: \.self) { kind in
                    Button(t("playlist.kind." + kind)) { model.playlistEditor = PlaylistEditorState(kind: kind, parentId: item.id) }
                }
            }.padding().disabled(!model.playlistEditable)
        }
    }
    private func entries(_ item: PlaylistSummaryDTO) -> some View {
        VStack(spacing: 0) {
            HStack {
                TextField(t("search"), text: $model.playlistQuery).textFieldStyle(.roundedBorder)
                if item.editable && item.kind != "folder" {
                    Menu(t("playlist.sort")) {
                        ForEach(PlaylistSortOption.all, id: \.value) { sort in
                            Button(t(sort.key)) { var edit = PlaylistEditDTO(action: "update", playlistId: item.id); edit.sortOrder = sort.value; model.mutatePlaylist(edit) }
                        }
                        if !item.sortSupported { Text(t("playlist.sort.unknown") + " \(item.sortOrder)") }
                        if item.canEditEntries {
                            Divider()
                            Button(t("playlist.sort.save.current")) { model.saveDisplayedPlaylistOrder() }.disabled(!model.canSaveDisplayedPlaylistOrder)
                        }
                    }.disabled(!model.playlistEditable)
                }
                if !model.playlistSortOrder.isEmpty {
                    Button(t("playlist.sort.clear")) { model.playlistSortOrder = [] }
                }
            }.padding(12)
            Table(visible, selection: $model.selectedEntries, sortOrder: $model.playlistSortOrder) {
                TableColumn("#", value: \.index) { entry in Text("\(entry.index + 1)").monospacedDigit() }.width(45)
                TableColumn(t("title"), value: \.sortTitle) { entry in
                    HStack {
                        if let track = entry.track { CoverView(model: model, id: track.artworkId, radius: 3).frame(width: 26, height: 26) }
                        Text(entry.track?.title ?? t("playlist.missing"))
                    }
                    .onDrag { NSItemProvider(object: ("entries:" + entry.id) as NSString) }
                    .onDrop(of: [UTType.text], isTargeted: nil) { providers in
                        guard model.canReorderEntries, let provider = providers.first else { return false }
                        _ = provider.loadObject(ofClass: NSString.self) { value, _ in
                            guard let text = value as? String, text.hasPrefix("entries:") else { return }
                            Task { @MainActor in
                                let id = String(text.dropFirst(8))
                                model.reorderEntries(dragged: model.selectedEntries.contains(id) ? Array(model.selectedEntries) : [id], before: entry.id)
                            }
                        }; return true
                    }
                }.width(min: 160, ideal: 240)
                TableColumn(t("artist"), value: \.sortArtist) { Text($0.track?.artist ?? "—") }.width(min: 90, ideal: 140)
                TableColumn(t("album"), value: \.sortAlbum) { Text($0.track?.album ?? "—") }.width(min: 100, ideal: 140)
                TableColumn(t("duration"), value: \.sortDuration) { Text(durationText($0.track?.lengthMs ?? 0)) }.width(65)
            }
            .contextMenu { entryActions(item) }
            if item.canEditEntries {
                HStack {
                    Button(t("playlist.remove")) { model.changeEntries("remove_entries") }.disabled(model.selectedEntries.isEmpty || !model.playlistEntriesComplete)
                    Button { model.changeEntries("move_entries_up") } label: { Image(systemName: "arrow.up") }.help(t("playlist.up")).disabled(!model.canReorderEntries || model.selectedEntries.isEmpty)
                    Button { model.changeEntries("move_entries_down") } label: { Image(systemName: "arrow.down") }.help(t("playlist.down")).disabled(!model.canReorderEntries || model.selectedEntries.isEmpty)
                    Spacer()
                    if !model.playlistEntriesComplete { ProgressView().controlSize(.small) }
                }.padding(12).disabled(!model.playlistEditable)
            }
        }
    }
    @ViewBuilder private func entryActions(_ item: PlaylistSummaryDTO) -> some View {
        if item.canEditEntries {
            Button(t("playlist.remove")) { model.changeEntries("remove_entries") }.disabled(!model.playlistEditable || model.selectedEntries.isEmpty)
            Button(t("playlist.up")) { model.changeEntries("move_entries_up") }.disabled(!model.canReorderEntries)
            Button(t("playlist.down")) { model.changeEntries("move_entries_down") }.disabled(!model.canReorderEntries)
        }
        Button(t("playlist.show.track")) {
            model.selectedTracks = Set(model.playlistEntries.filter { model.selectedEntries.contains($0.id) }.map(\.trackId)); model.workspace = .library; model.albumMode = false
        }
    }
}

struct PlaylistSortOption {
    let value: Int; let key: String
    static let all: [PlaylistSortOption] = [
        .init(value: 0, key: "playlist.sort.manual"),
        .init(value: 1, key: "playlist.sort.manual"),
        .init(value: 3, key: "playlist.field.title"),
        .init(value: 4, key: "playlist.field.album"),
        .init(value: 5, key: "playlist.field.artist"),
        .init(value: 6, key: "playlist.field.bitrate"),
        .init(value: 7, key: "playlist.field.genre"),
        .init(value: 8, key: "playlist.field.kind"),
        .init(value: 9, key: "playlist.field.date_modified"),
        .init(value: 10, key: "playlist.field.track_number"),
        .init(value: 11, key: "playlist.field.size"),
        .init(value: 12, key: "playlist.field.duration"),
        .init(value: 13, key: "playlist.field.year"),
        .init(value: 14, key: "playlist.field.sample_rate"),
        .init(value: 15, key: "playlist.field.comment"),
        .init(value: 16, key: "playlist.field.date_added"),
        .init(value: 17, key: "playlist.field.equalizer"),
        .init(value: 18, key: "playlist.field.composer"),
        .init(value: 20, key: "playlist.field.play_count"),
        .init(value: 21, key: "playlist.field.last_played"),
        .init(value: 22, key: "playlist.field.disc_number"),
        .init(value: 23, key: "playlist.field.rating"),
        .init(value: 24, key: "playlist.field.release_date"),
        .init(value: 25, key: "playlist.field.bpm"),
        .init(value: 26, key: "playlist.field.grouping"),
        .init(value: 27, key: "playlist.field.category"),
        .init(value: 28, key: "playlist.field.description")
    ]
}
struct PlaylistDraftBar: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    var body: some View {
        if let draft = model.playlistDraft, draft.dirty {
            Divider()
            HStack {
                Label(strings.text("playlist.unsaved"), systemImage: "circle.fill").font(.caption)
                Spacer()
                Button(strings.text("playlist.undo")) { model.playlistHistory("playlist_undo") }.disabled(!draft.canUndo)
                Button(strings.text("playlist.redo")) { model.playlistHistory("playlist_redo") }.disabled(!draft.canRedo)
                Button(strings.text("playlist.discard")) { model.playlistHistory("playlist_discard") }
                Menu(strings.text("playlist.check")) {
                    Button(strings.text("playlist.check.only")) { model.preparePlaylistReview() }
                    if !model.queue.isEmpty { Button(strings.text("playlist.check.combined")) { model.preparePlaylistReview(includeImports: true) } }
                }.menuStyle(.borderlessButton).fixedSize()
            }.padding(12).disabled(!model.playlistEditable)
        }
    }
}
