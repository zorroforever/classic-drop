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
                            .labelsHidden().disabled(model.busy || entry.status != "new")
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

struct InspectorView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    private func t(_ key: String) -> String { strings.text(key) }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(t("inspector")).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                if model.workspace == .incoming, let token = model.selectedQueue,
                   let entry = model.queue.first(where: { $0.token == token }) {
                    preview(entry)
                } else if let track = (model.tracks + model.albumTracks).first(where: { model.selectedTracks.contains($0.id) }) {
                    CoverView(id: track.artworkId)
                    Text(track.title).font(.title2.bold()).textSelection(.enabled)
                    Text(track.artist).foregroundStyle(.secondary)
                    Divider()
                    info("album", track.album); info("year", track.year > 0 ? "\(track.year)" : "—")
                    info("duration", track.duration); info("genre", track.genre)
                } else if let album = model.selectedAlbum {
                    CoverView(id: album.artworkId)
                    Text(album.title.isEmpty ? t("album.unknown") : album.title).font(.title2.bold())
                    Text(album.artist).foregroundStyle(.secondary)
                    Divider()
                    info("year", album.year > 0 ? "\(album.year)" : "—")
                    info("songs", "\(album.trackCount)"); info("duration", album.duration)
                    Button(t("album.open")) { model.open(album) }.frame(maxWidth: .infinity)
                } else {
                    Image(systemName: "info.circle").font(.largeTitle).foregroundStyle(.tertiary).padding(.top, 50)
                    Text(t("inspector.empty")).foregroundStyle(.secondary)
                }
            }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
        }.background(Color(nsColor: .windowBackgroundColor).opacity(0.35))
    }
    private func info(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top) { Text(t(label)).foregroundStyle(.secondary); Spacer(); Text(value).multilineTextAlignment(.trailing).textSelection(.enabled) }.font(.callout)
    }
    private func preview(_ entry: PreviewDTO) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            CoverView(id: entry.token, preview: true)
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
            Divider()
            Text(t(entry.status)).font(.headline)
            if entry.status != "new" && entry.status != "error" {
                Text(t("duplicate.hint")).font(.caption).foregroundStyle(.secondary)
                Toggle(t("duplicate.override"), isOn: Binding(get: { model.edits[entry.token]?.allowDuplicate ?? false }, set: { value in
                    model.edit(entry.token) { $0.allowDuplicate = value; $0.selected = value }
                })).font(.callout)
            }
            Text(entry.detail).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
            Text(entry.path).font(.caption).foregroundStyle(.secondary).textSelection(.enabled).lineLimit(4).truncationMode(.middle)
        }.disabled(model.busy || entry.status == "error")
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
