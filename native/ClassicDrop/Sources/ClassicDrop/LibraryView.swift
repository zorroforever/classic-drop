import SwiftUI
import ClassicDropCore

struct LibraryView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    private func t(_ key: String) -> String { strings.text(key) }
    var body: some View {
        VStack(spacing: 0) {
            if model.browserReady {
                HStack(spacing: 12) {
                    Text(String(format: t("selection.count"), model.selectedTracks.count)).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    if model.playlistSupported {
                        Button(t("playlist.targets")) { model.playlistTrackTargets = true }.disabled(!model.playlistEditable || model.selectedTracks.isEmpty)
                    }
                    if !model.selectedTracks.isEmpty {
                        Button(t("selection.clear")) { model.selectedTracks = [] }.disabled(model.busy)
                    }
                    Button { model.addLibrarySelection() } label: { Label(t("package.add"), systemImage: "text.badge.minus") }
                        .disabled(model.busy || model.selectedMusicCount == 0)
                }.padding(.horizontal, 24).padding(.vertical, 10)
                Divider()
            }
            if let album = model.openAlbum { detail(album) }
            else if model.albumMode { grid }
            else { TrackTable(tracks: model.tracks, selection: selection(model.tracks)) }
        }
        .overlay {
            if model.browserPreparing {
                ProgressView(t("browser.preparing"))
                    .controlSize(.large)
                    .padding(20)
            }
        }
    }
    private func selection(_ rows: [TrackDTO]) -> Binding<Set<String>> {
        let visible = Set(rows.map(\.id))
        return Binding(get: { model.selectedTracks.intersection(visible) },
                       set: { model.replaceVisibleSelection($0, visible: visible) })
    }
    private var grid: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Text(t("all.albums")).font(.headline)
                    Spacer()
                    Text(String(format: t("album.count"), model.albumTotal, model.state?.trackCount ?? 0)).font(.caption).foregroundStyle(.secondary)
                }
                if model.albums.isEmpty {
                    EmptyWorkspace(symbol: "square.stack", title: t("empty.library"), detail: "") {
                        Button(t("add.files")) { model.addFiles(folder: false) }.disabled(!model.writable)
                    }.frame(minHeight: 260)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 155, maximum: 230), spacing: 24)], alignment: .leading, spacing: 22) {
                    ForEach(model.albums) { album in
                        Button {
                            model.selectAlbum(album)
                        } label: {
                            VStack(alignment: .leading, spacing: 7) {
                                CoverView(model: model, id: album.artworkId)
                                Text(album.title.isEmpty ? t("album.unknown") : album.title)
                                    .font(.headline).lineLimit(1).foregroundStyle(.primary)
                                Text(album.artist.isEmpty ? t("artist.unknown") : album.artist)
                                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                Text(String(format: t("song.count"), album.trackCount) + (album.year > 0 ? " · \(album.year)" : ""))
                                    .font(.caption).foregroundStyle(.secondary)
                                AlbumAudioSummary(album: album)
                            }.padding(11).contentShape(Rectangle())
                                .background(model.selectedAlbum?.id == album.id ? Color.accentColor.opacity(0.12) : .clear, in: RoundedRectangle(cornerRadius: 16))
                                .overlay(RoundedRectangle(cornerRadius: 16).stroke(model.selectedAlbum?.id == album.id ? Color.accentColor.opacity(0.2) : .clear))
                        }
                        .buttonStyle(.plain)
                        .simultaneousGesture(TapGesture(count: 2).onEnded { model.open(album) })
                        .contextMenu { Button(t("album.open")) { model.open(album) } }
                        .accessibilityLabel(album.title + ", " + album.artist)
                    }
                }
            }.padding(24)
        }
    }
    private func detail(_ album: AlbumDTO) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Button { model.openAlbum = nil } label: { Label(t("albums"), systemImage: "chevron.left") }
                Spacer()
                Text(t("library") + " / " + album.artist + " / " + album.title).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            HStack(alignment: .center, spacing: 24) {
                CoverView(model: model, id: album.artworkId).frame(width: 140)
                VStack(alignment: .leading, spacing: 10) {
                    Text(album.title).font(.system(size: 30, weight: .bold)).lineLimit(2)
                    Text(album.artist).font(.title3).foregroundStyle(.secondary)
                    Text((album.year > 0 ? "\(album.year) · " : "") + String(format: t("song.count"), album.trackCount) + " · " + album.duration)
                        .font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
            }
            AlbumAudioSummary(album: album)
            TrackTable(tracks: model.albumTracks, selection: selection(model.albumTracks))
        }.padding(24).background(Color(nsColor: .textBackgroundColor))
    }
}

struct TrackTable: View {
    let tracks: [TrackDTO]
    @Binding var selection: Set<String>
    var showSource = false
    @EnvironmentObject var strings: Strings
    @EnvironmentObject var model: AppModel
    var body: some View {
        Group {
        if showSource {
            Table(tracks, selection: $selection) {
                TableColumn(strings.text("title"), value: \.title).width(min: 130, ideal: 220)
                TableColumn(strings.text("artist"), value: \.artist).width(min: 90, ideal: 150)
                TableColumn(strings.text("album"), value: \.album).width(min: 90, ideal: 160)
                TableColumn(strings.text("audio.codec")) { track in
                    TrackCodecCell(trackID: track.id, model: model, strings: strings)
                }.width(min: 55, ideal: 65)
                TableColumn(strings.text("audio.bit_depth")) { track in
                    Text(model.audioFormats[track.id]?.bitDepthText ?? model.audioFormatPlaceholder).monospacedDigit()
                }.width(min: 55, ideal: 65)
                TableColumn(strings.text("audio.sample_rate")) { track in
                    Text(model.audioFormats[track.id]?.sampleRateText ?? model.audioFormatPlaceholder).monospacedDigit()
                }.width(min: 70, ideal: 85)
                TableColumn(strings.text("source"), value: \.source).width(min: 100, ideal: 160)
            }
        } else {
            Table(tracks, selection: $selection) {
            TableColumn("#") { Text($0.trackNumber > 0 ? "\($0.trackNumber)" : "—").foregroundStyle(.secondary) }.width(30)
            TableColumn(strings.text("title")) { track in
                Text(track.title).onDrag {
                    let ids = model.selectedTracks.contains(track.id) ? model.playlistAvailableTracks.filter { model.selectedTracks.contains($0.id) }.map(\.id) : [track.id]
                    return NSItemProvider(object: ("tracks:" + ids.joined(separator: ",")) as NSString)
                }
            }.width(min: 130, ideal: 220)
            TableColumn(strings.text("artist"), value: \.artist).width(min: 90, ideal: 150)
            TableColumn(strings.text("album"), value: \.album).width(min: 90, ideal: 160)
                TableColumn(strings.text("audio.codec")) { track in
                    TrackCodecCell(trackID: track.id, model: model, strings: strings)
                }.width(min: 55, ideal: 65)
                TableColumn(strings.text("audio.bit_depth")) { track in
                    Text(model.audioFormats[track.id]?.bitDepthText ?? model.audioFormatPlaceholder).monospacedDigit()
                }.width(min: 55, ideal: 65)
                TableColumn(strings.text("audio.sample_rate")) { track in
                    Text(model.audioFormats[track.id]?.sampleRateText ?? model.audioFormatPlaceholder).monospacedDigit()
                }.width(min: 70, ideal: 85)
            TableColumn(strings.text("duration"), value: \.duration).width(55)
            }
        }
        }
        .textSelection(.enabled)
    }
}

struct TrackCodecCell: View {
    let trackID: String
    @ObservedObject var model: AppModel
    @ObservedObject var strings: Strings
    var body: some View {
        let generation = model.state?.generation
        Text(model.audioFormats[trackID]?.codecText ?? model.audioFormatPlaceholder)
            .help(!model.audioFormatReadingEnabled ? strings.text("audio.disabled") : model.audioFormats[trackID]?.detail.isEmpty == false ? strings.text("audio.unavailable") : strings.text("audio.codec"))
            .onAppear { model.acquireAudioFormats([trackID]) }
            .onDisappear { if generation == model.state?.generation { model.releaseAudioFormats([trackID]) } }
            .id([generation ?? "", trackID])
    }
}

struct AlbumAudioSummary: View {
    let album: AlbumDTO
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    var body: some View {
        if model.audioFormatReadingEnabled {
            let ids = model.audioTrackIDs(for: album)
            let generation = model.state?.generation
            let summary = audioFormatSummary(ids: ids, formats: model.audioFormats, unknown: strings.text("audio.unknown"))
            Text(summary ?? strings.text("audio.loading"))
                .font(.caption).foregroundStyle(.secondary).lineLimit(3)
                .help(summary ?? strings.text("audio.loading"))
                .onAppear { model.acquireAudioFormats(ids) }
                .onDisappear { if generation == model.state?.generation { model.releaseAudioFormats(ids) } }
                .id([generation ?? "", album.id] + ids)
        }
    }
}
