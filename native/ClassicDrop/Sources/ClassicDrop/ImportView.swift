import SwiftUI
import ClassicDropCore

struct ImportView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @State private var status = "all"
    @State private var search = ""
    private func t(_ key: String) -> String { strings.text(key) }
    private var visible: [PreviewDTO] {
        model.queue.filter { (status == "all" || $0.status == status) && (search.isEmpty || "\($0.title) \($0.artist) \($0.album)".localizedCaseInsensitiveContains(search)) }
    }
    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 6) {
                Toggle(t("alac.original"), isOn: Binding(get: { model.alacOriginalImport }, set: { model.setAlacOriginalImport($0) }))
                    .toggleStyle(.switch).disabled(!model.canChangeAlacOriginalImport)
                Text(t(model.queue.isEmpty ? (model.alacOriginalImport ? "alac.original.on" : "alac.original.off") : "alac.original.locked"))
                    .font(.caption).foregroundStyle(.secondary)
            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            if model.playlistSupported {
                HStack {
                    Button(t("playlist.import.destination")) { model.playlistTargetSheet = true }.disabled(!model.playlistEditable)
                    Text(model.queueRequiresReselection ? t("playlist.reselect") : model.importDestination.playlistIds.isEmpty && model.importDestination.newName == nil ? t("playlist.import.library") : t("playlist.import.selected")).font(.caption).foregroundStyle(model.queueRequiresReselection ? Color.orange : Color.secondary)
                    Spacer()
                    if model.queueNeedsPreparation { Button(t("playlist.reprepare")) { model.reprepareQueue() }.disabled(!model.playlistEditable) }
                    Button(t(model.playlistDraft?.dirty == true ? "playlist.check.combined" : "playlist.check.import")) { model.preparePlaylistReview(includeImports: true) }.disabled(!model.writable || model.queueNeedsPreparation)
                }.padding(.horizontal, 16).padding(.bottom, 12)
            }
            Divider()
        if model.queue.isEmpty {
            EmptyWorkspace(symbol: "music.note.list", title: t("queue.empty"), detail: t("queue.hint")) {
                HStack {
                    Button(t("add.files")) { model.addFiles(folder: false) }
                    Button(t("add.folder")) { model.addFiles(folder: true) }
                }.disabled(!model.writable)
            }
        } else {
            VStack(spacing: 0) {
                HStack {
                    TextField(t("search"), text: $search).textFieldStyle(.roundedBorder)
                    Picker(t("status"), selection: $status) {
                        Text(t("songs")).tag("all")
                        ForEach(["new", "confirmed_duplicate", "history_match", "possible_duplicate", "check_incomplete", "error"], id: \.self) { Text(t($0)).tag($0) }
                    }.frame(width: 150)
                    if model.playlistSupported {
                        Button { model.moveQueue(up: true) } label: { Image(systemName: "arrow.up") }.help(t("playlist.up"))
                            .disabled(model.busy || model.selectedQueue == nil || !search.isEmpty || status != "all" || model.queueNeedsPreparation || model.queue.count != model.state?.queueCount)
                        Button { model.moveQueue(up: false) } label: { Image(systemName: "arrow.down") }.help(t("playlist.down"))
                            .disabled(model.busy || model.selectedQueue == nil || !search.isEmpty || status != "all" || model.queueNeedsPreparation || model.queue.count != model.state?.queueCount)
                    }
                    Menu {
                        Button(t("select.all")) { for entry in model.queue where entry.status == "new" { model.edit(entry.token) { $0.selected = true } } }
                        Button(t("deselect.all")) { for entry in model.queue { model.edit(entry.token) { $0.selected = false } } }
                        Divider()
                        Button(t("queue.clear")) { model.discard() }
                    } label: { Image(systemName: "ellipsis.circle") }.disabled(model.busy)
                }.padding(16)
                Table(visible, selection: $model.selectedQueue) {
                    TableColumn(t("include")) { entry in
                        Toggle("", isOn: Binding(get: { model.edits[entry.token]?.selected ?? entry.selected }, set: { value in model.edit(entry.token) { $0.selected = value } }))
                            .labelsHidden().disabled(model.busy || entry.status != "new" && !model.importReuse.contains { $0.token == entry.token })
                    }.width(42)
                    TableColumn(t("title")) { entry in
                        TextField(t("title"), text: Binding(get: { model.edits[entry.token]?.title ?? entry.title }, set: { value in model.edit(entry.token) { $0.title = value } }))
                            .textFieldStyle(.plain).disabled(model.busy || entry.status == "error")
                    }.width(min: 125, ideal: 210)
                    TableColumn(t("artist")) { entry in Text(model.edits[entry.token]?.artist ?? entry.artist) }.width(min: 90, ideal: 140)
                    TableColumn(t("album")) { entry in Text(model.edits[entry.token]?.album ?? entry.album) }.width(min: 100, ideal: 170)
                    TableColumn(t("status")) { entry in
                        Label(t(entry.status == "new" && entry.mode == "convert" ? "convert" : entry.status), systemImage: entry.status == "new" ? "checkmark.circle" : entry.status == "error" ? "exclamationmark.circle" : "doc.on.doc")
                            .font(.caption).foregroundStyle(entry.status == "new" ? Color.secondary : .orange)
                            .help(entry.detail)
                    }.width(min: 110, ideal: 150)
                }
                .onChange(of: model.selectedQueue) { _ in model.inspector = true }
                HStack {
                    Text(String(format: t("song.count"), model.queue.count)).foregroundStyle(.secondary)
                    Spacer()
                    Button(t("add.files")) { model.addFiles(folder: false) }.disabled(!model.writable)
                    Button(t("add.folder")) { model.addFiles(folder: true) }.disabled(!model.writable)
                }.font(.caption).padding(14)
            }
        }
        }
    }
}

struct InspectorView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    private func t(_ key: String) -> String { strings.text(key) }
    var body: some View {
        Form {
            if model.workspace == .incoming, let token = model.selectedQueue,
               let entry = model.queue.first(where: { $0.token == token }) {
                preview(entry)
            } else if let track = (model.tracks + model.albumTracks).first(where: { model.selectedTracks.contains($0.id) }) {
                Section {
                    identity(artworkID: track.artworkId, title: track.title, artist: track.artist)
                }
                Section {
                    info("album", track.album); info("year", track.year > 0 ? "\(track.year)" : "—")
                    info("duration", track.duration); info("genre", track.genre)
                    HStack { Text(t("audio.codec")).foregroundStyle(.secondary); Spacer(); TrackCodecCell(trackID: track.id, model: model, strings: strings) }.font(.callout)
                    info("audio.bit_depth", model.audioFormats[track.id]?.bitDepthText ?? model.audioFormatPlaceholder)
                    info("audio.sample_rate", model.audioFormats[track.id]?.sampleRateText ?? model.audioFormatPlaceholder)
                } header: {
                    Text(t("details"))
                }
            } else if let album = model.selectedAlbum {
                Section {
                    identity(artworkID: album.artworkId, title: album.title.isEmpty ? t("album.unknown") : album.title, artist: album.artist)
                }
                Section {
                    info("year", album.year > 0 ? "\(album.year)" : "—")
                    info("songs", "\(album.trackCount)"); info("duration", album.duration)
                    AlbumAudioSummary(album: album)
                    Button(t("album.open")) { model.open(album) }.frame(maxWidth: .infinity)
                } header: {
                    Text(t("details"))
                }
            } else {
                Section {
                    Label(t("inspector.empty"), systemImage: "info.circle")
                        .foregroundStyle(.secondary)
                }
            }
        }
    }
    private func identity(artworkID: String, title: String, artist: String) -> some View {
        VStack(alignment: .center, spacing: 10) {
            CoverView(model: model, id: artworkID).frame(maxWidth: 260)
            Text(title).font(.title2.bold()).textSelection(.enabled)
                .multilineTextAlignment(.center).frame(maxWidth: .infinity)
            Text(artist).foregroundStyle(.secondary)
                .multilineTextAlignment(.center).frame(maxWidth: .infinity)
        }
        .frame(maxWidth: .infinity)
    }

    private func info(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top) { Text(t(label)).foregroundStyle(.secondary); Spacer(); Text(value).multilineTextAlignment(.trailing).textSelection(.enabled) }.font(.callout)
    }
    private func preview(_ entry: PreviewDTO) -> some View {
        Group {
            Section {
                CoverView(model: model, id: entry.token, preview: true).frame(maxWidth: .infinity)
            }
            Section {
                ForEach(["title", "artist", "album", "album.artist"], id: \.self) { key in
                    VStack(alignment: .leading, spacing: 5) {
                        Text(t(key)).font(.caption).foregroundStyle(.secondary)
                        TextField(t(key), text: textBinding(entry, key: key)).textFieldStyle(.roundedBorder)
                    }
                }
                HStack {
                    numberField(entry, disc: true)
                    numberField(entry, disc: false)
                }
                HStack {
                    Button(t("cover.replace")) { model.cover(clear: false) }
                    Button { model.cover(clear: true) } label: { Image(systemName: "trash") }.help(t("cover.clear"))
                }
            } header: {
                Text(t("details"))
            }
            Section {
                Text(t(entry.status)).font(.headline)
                if entry.status != "new" && entry.status != "error" {
                    if model.playlistSupported { ImportReusePicker(token: entry.token) }
                    Text(t("duplicate.hint")).font(.caption).foregroundStyle(.secondary)
                    Toggle(t("duplicate.override"), isOn: Binding(get: { model.edits[entry.token]?.allowDuplicate ?? false }, set: { value in
                        model.edit(entry.token) { $0.allowDuplicate = value; $0.selected = value }
                    })).font(.callout)
                }
                Text(entry.detail).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                Text(entry.path).font(.caption).foregroundStyle(.secondary).textSelection(.enabled).lineLimit(4).truncationMode(.middle)
            } header: {
                Text(t("status"))
            }
        }
        .disabled(model.busy || entry.status == "error" || model.queueNeedsPreparation)
    }
    private func textBinding(_ entry: PreviewDTO, key: String) -> Binding<String> {
        let value = model.edits[entry.token] ?? EditDTO(entry)
        return Binding(get: {
            switch key { case "title": return value.title; case "artist": return value.artist; case "album": return value.album; default: return value.albumArtist }
        }, set: { text in
            model.edit(entry.token) { edit in
                switch key { case "title": edit.title = text; case "artist": edit.artist = text; case "album": edit.album = text; default: edit.albumArtist = text }
            }
        })
    }
    private func numberField(_ entry: PreviewDTO, disc: Bool) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(t(disc ? "disc.number" : "track.number")).font(.caption).foregroundStyle(.secondary)
            TextField("", value: Binding(get: {
                let value = model.edits[entry.token] ?? EditDTO(entry)
                return disc ? value.discNumber : value.trackNumber
            }, set: { number in model.edit(entry.token) { if disc { $0.discNumber = max(0, min(65535, number)) } else { $0.trackNumber = max(0, min(65535, number)) } } }), format: .number)
                .textFieldStyle(.roundedBorder)
        }
    }
}
