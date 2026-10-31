import SwiftUI
import ClassicDropCore

struct PlaylistReviewView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    let review: PlaylistReviewDTO
    private func t(_ key: String) -> String { strings.text(key) }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(t("playlist.review")).font(.title2.bold())
            if review.noChanges { Text(t("playlist.no.changes")) }
            if review.added > 0 || review.reused > 0 { Text(String(format: t("playlist.review.import"), review.added, review.reused)) }
            Text(t("playlist.review.recovery")).font(.caption).foregroundStyle(.secondary)
            List {
                ForEach(["draft", "sidecar", "smart"], id: \.self) { origin in
                    let changes = review.changes.filter { $0.origin == origin }
                    if !changes.isEmpty {
                        Section(t("playlist.origin." + origin)) {
                            ForEach(Array(changes.enumerated()), id: \.offset) { _, change in
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(change.name.isEmpty ? change.identity : change.name).font(.headline).textSelection(.enabled)
                                    Text(t("playlist.action." + change.action) + " · " + t("playlist.subject." + change.subject)).font(.caption)
                                    if !change.fields.isEmpty { Text(change.fields.map { t("playlist.change." + $0) }.joined(separator: ", ")).font(.caption).foregroundStyle(.secondary) }
                                }
                            }
                        }
                    }
                }
            }
            PlaylistInlineError()
            GlassControls {
                HStack {
                    Button(t("cancel")) { model.invalidatePlaylistReview(); if model.pendingLifecycle != nil { model.cancelLifecycle() } }.keyboardShortcut(.cancelAction)
                    Spacer()
                    if !model.playlistReviewComplete { ProgressView().controlSize(.small) }
                    if review.noChanges {
                        Button(t("playlist.finish.empty")) { model.finishEmptyPlaylistReview() }
                            .keyboardShortcut(.defaultAction).disabled(!model.playlistEditable || !model.playlistReviewComplete)
                    } else {
                        Button(t(review.added > 0 ? "playlist.save.import" : "playlist.save")) { model.savePlaylistReview() }
                            .keyboardShortcut(.defaultAction).disabled(!model.writable || !model.playlistReviewComplete)
                    }
                }
            }
        }.padding(24).frame(width: 720, height: 580).interactiveDismissDisabled(model.busy)
    }
}

struct PlaylistDeleteView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    let item: PlaylistSummaryDTO
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(strings.text("playlist.delete")).font(.title2.bold())
            Text(strings.text("playlist.delete.hint"))
            List(model.playlistDeletionScope(item)) { child in Label(child.fullPath, systemImage: child.symbol) }
            PlaylistInlineError()
            HStack {
                Button(strings.text("cancel")) { model.playlistDelete = nil }.keyboardShortcut(.cancelAction)
                Spacer()
                Button(strings.text("playlist.delete.draft")) {
                    model.mutatePlaylist(PlaylistEditDTO(action: "delete", playlistId: item.id)) { model.playlistDelete = nil }
                }.disabled(!model.playlistEditable).keyboardShortcut(.defaultAction)
            }
        }.padding(24).frame(width: 620, height: 420).interactiveDismissDisabled(model.busy)
    }
}

struct PlaylistLifecycleView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(strings.text("playlist.unsaved")).font(.title2.bold())
            Text(strings.text("playlist.lifecycle.hint"))
            PlaylistInlineError()
            HStack {
                Button(strings.text("cancel")) { model.cancelLifecycle() }.keyboardShortcut(.cancelAction)
                Button(strings.text("playlist.discard")) { model.discardForLifecycle() }
                Spacer()
                Button(strings.text("playlist.check.save")) { model.preparePlaylistReview() }.keyboardShortcut(.defaultAction)
            }.disabled(!model.playlistEditable)
        }.padding(24).frame(width: 630)
    }
}

struct ImportPlaylistDestination: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @Environment(\.dismiss) private var dismiss
    @State private var destination = ImportDestinationDTO()
    @State private var initialized = false
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(strings.text("playlist.import.destination")).font(.title2.bold())
            Text(strings.text("playlist.import.destination.hint")).font(.caption).foregroundStyle(.secondary)
            List(model.playlistItems.filter(\.canEditEntries)) { item in
                Toggle(item.fullPath, isOn: Binding(get: { destination.playlistIds.contains(item.id) }, set: { enabled in
                    destination.playlistIds.removeAll { $0 == item.id }
                    if enabled { destination.playlistIds.append(item.id); destination.newName = nil; destination.parentId = nil; destination.keepEmptyNew = false }
                }))
            }
            TextField(strings.text("playlist.import.new"), text: Binding(get: { destination.newName ?? "" }, set: {
                destination.newName = $0.isEmpty ? nil : $0
                if !$0.isEmpty { destination.playlistIds = [] }
                else { destination.parentId = nil; destination.keepEmptyNew = false }
            })).textFieldStyle(.roundedBorder)
            Picker(strings.text("playlist.parent"), selection: Binding(get: { destination.parentId ?? "" }, set: { destination.parentId = $0.isEmpty ? nil : $0 })) {
                Text(strings.text("playlist.root")).tag("")
                ForEach(model.playlistItems.filter { $0.kind == "folder" }) { Text($0.fullPath).tag($0.id) }
            }.disabled(destination.newName == nil)
            Toggle(strings.text("playlist.import.keep.empty"), isOn: $destination.keepEmptyNew).disabled(destination.newName == nil)
            PlaylistInlineError()
            HStack {
                Button(strings.text("cancel")) { dismiss() }.keyboardShortcut(.cancelAction)
                Spacer()
                Button(strings.text("playlist.apply")) { model.saveImportDestination(destination); dismiss() }.keyboardShortcut(.defaultAction).disabled(!model.playlistEditable)
            }
        }.padding(24).frame(width: 650, height: 530).onAppear { if !initialized { initialized = true; destination = model.importDestination } }
    }
}

struct ImportReusePicker: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    let token: String
    @State private var selection: String = ""
    var body: some View {
        Picker(strings.text("playlist.reuse"), selection: Binding(get: {
            model.importReuse.first { $0.token == token }?.trackId ?? ""
        }, set: { id in
            var reuse = model.importReuse.filter { $0.token != token }
            if !id.isEmpty { reuse.append(ImportReuseDTO(token: token, trackId: id)) }
            model.saveImportDestination(model.importDestination, reuse: reuse)
        })) {
            Text(strings.text("playlist.reuse.none")).tag("")
            ForEach(model.playlistAvailableTracks) { track in Text("\(track.title) · \(track.artist) · \(track.album) [\(track.id)]").tag(track.id) }
        }.disabled(!model.playlistEditable)
    }
}

struct PlaylistInlineError: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    var body: some View {
        if !model.error.isEmpty {
            HStack(alignment: .top) {
                ScrollView { Text(model.error).font(.callout).foregroundStyle(.red).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }.frame(maxHeight: 100)
                Button { model.error = "" } label: { Image(systemName: "xmark.circle") }.help(strings.text("close"))
            }
        }
    }
}
