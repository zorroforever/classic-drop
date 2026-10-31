import SwiftUI
import ClassicDropCore

struct RemovalView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    private func t(_ key: String) -> String { strings.text(key) }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                TextField(t("title"), text: $model.titleFilter)
                TextField(t("artist"), text: $model.artistFilter)
                TextField(t("album"), text: $model.albumFilter)
                Button(t("filter.apply")) { model.selectedMatches = []; model.filter() }
            }.textFieldStyle(.roundedBorder)
            HStack {
                Menu(t("genre") + badge(model.genreFilter.count)) {
                    ForEach(model.genres, id: \.self) { genre in
                        Toggle(genre.isEmpty ? "—" : genre, isOn: membership(genre, set: $model.genreFilter))
                    }
                }
                Menu(t("year") + badge(model.yearFilter.count)) {
                    ForEach(model.years, id: \.self) { year in
                        Toggle(year == 0 ? "—" : "\(year)", isOn: membership(year, set: $model.yearFilter))
                    }
                }
                Menu(t("playlist") + badge(model.playlistFilter.count)) {
                    ForEach(model.playlists) { playlist in
                        Toggle(playlist.name, isOn: membership(playlist.id, set: $model.playlistFilter))
                    }
                }
                Button(t("filter.reset")) {
                    model.titleFilter = ""; model.artistFilter = ""; model.albumFilter = ""
                    model.genreFilter = []; model.yearFilter = []; model.playlistFilter = []; model.filter()
                }
            }
            HStack {
                Text(String(format: t("song.count"), model.matchTotal)).font(.caption).foregroundStyle(.secondary)
                Spacer()
                if model.matches.count < model.matchTotal { Button(t("load.more")) { model.filter(more: true) } }
                Button(t("package.add")) {
                    let source = [model.titleFilter, model.artistFilter, model.albumFilter,
                                  model.genreFilter.sorted().joined(separator: ", "), model.yearFilter.sorted().map(String.init).joined(separator: ", "),
                                  model.playlists.filter { model.playlistFilter.contains($0.id) }.map(\.name).joined(separator: ", ")].filter { !$0.isEmpty }.joined(separator: " · ")
                    model.addToPackage(model.selectedMatches, source: source.isEmpty ? t("songs") : source)
                }.disabled(model.selectedMatches.isEmpty || model.busy)
            }
            TrackTable(tracks: model.matches, selection: $model.selectedMatches).frame(minHeight: 110)
            Divider()
            HStack {
                Text(t("package") + " · \(model.state?.packageCount ?? 0)").font(.headline)
                Spacer()
                if model.package.count < (model.state?.packageCount ?? 0) { Button(t("load.more")) { model.loadPackage(more: true) } }
                Button(t("package.remove")) { model.packageAction(clear: false) }.disabled(model.selectedPackage.isEmpty || model.busy)
                Button(t("package.clear")) { model.packageAction(clear: true) }.disabled(model.package.isEmpty || model.busy)
            }
            TrackTable(tracks: model.package, selection: $model.selectedPackage, showSource: true).frame(minHeight: 110)
            Text(t("removal.warning")).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                Button(t("package.review")) { model.prepareRemoval() }
                    .buttonStyle(.borderedProminent)
                    .disabled(!model.canReviewRemoval)
            }
        }.padding(18)
            .onChange(of: model.genreFilter) { _ in model.filter() }
            .onChange(of: model.yearFilter) { _ in model.filter() }
            .onChange(of: model.playlistFilter) { _ in model.filter() }
    }
    private func badge(_ count: Int) -> String { count > 0 ? " (\(count))" : "" }
    private func membership<T: Hashable>(_ value: T, set: Binding<Set<T>>) -> Binding<Bool> {
        Binding(get: { set.wrappedValue.contains(value) }, set: { if $0 { set.wrappedValue.insert(value) } else { set.wrappedValue.remove(value) } })
    }
}

struct RemovalReviewView: View {
    let review: ReviewDTO
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @State private var rows: [TrackDTO] = []
    @State private var selection = Set<String>()
    private func t(_ key: String) -> String { strings.text(key) }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(t("removal.review")).font(.title2.bold())
            Text(t("removal.warning")).fixedSize(horizontal: false, vertical: true)
            Text(String(format: t("recovery.size"), ByteCountFormatter.string(fromByteCount: review.sizeBytes, countStyle: .file))).font(.callout)
            if !review.playlists.isEmpty {
                DisclosureGroup(t("affected.playlists") + " (\(review.playlists.count))") {
                    ScrollView { Text(review.playlists.joined(separator: "\n")).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled) }.frame(maxHeight: 100)
                }
            }
            TrackTable(tracks: rows, selection: $selection, showSource: true)
            HStack {
                Text(String(format: t("song.count"), rows.count)).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button(t("cancel")) { model.review = nil }.keyboardShortcut(.defaultAction)
                    .keyboardShortcut(.cancelAction)
                Button(t("removal.confirm"), role: .destructive) { model.confirmRemoval(review.token) }
                    .disabled(model.busy || rows.count != review.trackCount || Set(rows.map(\.id)).count != review.trackCount)
            }
        }.padding(24).frame(minWidth: 740, minHeight: 510)
            .onAppear { rows = review.tracks; loadMore() }
    }
    private func loadMore() {
        guard rows.count < review.trackCount else { return }
        model.perform("review", configure: { $0.offset = rows.count; $0.token = review.token }) { result in
            let next = result.tracks ?? []
            rows += next
            if !next.isEmpty { loadMore() }
        }
    }
}

struct RecoveryView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @State private var confirmingKeep = false
    @State private var keepState: StateDTO?
    private func t(_ key: String) -> String { strings.text(key) }
    var body: some View {
        Form {
            Section {
                Text(t("recovery.hint")).foregroundStyle(.secondary)
            } header: {
                Label(t("recovery"), systemImage: "clock.arrow.circlepath")
            }
            if model.state?.canRestore == true {
                Section {
                    if model.state?.writesAllowed == false { Text(t("recovery.blocked")).font(.headline) }
                    Text(model.state?.recoveryPath ?? "")
                        .font(.system(.callout, design: .monospaced))
                        .textSelection(.enabled)
                    Button(t("restore")) { model.restore() }.disabled(!model.ready || model.busy)
                    if model.state?.canKeepContents == true {
                        Button(t("keep")) {
                            keepState = model.state; confirmingKeep = true
                        }.disabled(!model.ready || model.busy)
                    }
                } header: {
                    Text(t("recovery.location"))
                }
            } else {
                Section {
                    Label(t("recovery.none"), systemImage: "checkmark.circle")
                        .foregroundStyle(.secondary)
                }
            }
        }
        .alert(t("keep"), isPresented: $confirmingKeep) {
            Button(t("cancel"), role: .cancel) {}
            Button(t("keep")) {
                if let expected = keepState { model.keepCurrentContents(expected) }
            }
        } message: {
            Text(t("keep.warning"))
        }
    }
}
