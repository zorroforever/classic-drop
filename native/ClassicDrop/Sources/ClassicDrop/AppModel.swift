import AppKit
import SwiftUI
import ClassicDropCore

enum Workspace: String, CaseIterable, Identifiable {
    case library, incoming, removal, recovery
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .library: return "books.vertical"
        case .incoming: return "plus"
        case .removal: return "trash"
        case .recovery: return "clock.arrow.circlepath"
        }
    }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var workspace: Workspace = .library
    @Published var state: StateDTO?
    @Published var devices: [DeviceDTO] = []
    @Published var albums: [AlbumDTO] = []
    @Published var tracks: [TrackDTO] = []
    @Published var albumTracks: [TrackDTO] = []
    @Published var queue: [PreviewDTO] = []
    @Published var edits: [String: EditDTO] = [:]
    @Published var matches: [TrackDTO] = []
    @Published var package: [TrackDTO] = []
    @Published var genres: [String] = []
    @Published var years: [Int] = []
    @Published var playlists: [FacetDTO] = []
    @Published var task: TaskState?
    @Published var browserPreparing = false
    @Published var browserReady = false
    @Published var ready = false
    @Published var closing = false
    @Published var cancelRequested = false
    @Published var error = ""
    @Published var audioFormats: [String: AudioFormatDTO] = [:]
    @Published private(set) var audioFormatReadingEnabled = false
    @Published var images: [String: NSImage] = [:]
    @Published var query = ""
    @Published var albumMode = true
    @Published var inspector = true
    @Published var selectedAlbum: AlbumDTO?
    @Published var openAlbum: AlbumDTO?
    @Published var selectedTracks = Set<String>()
    @Published private(set) var alacOriginalImport = false
    @Published var selectedQueue: String?
    @Published var selectedMatches = Set<String>()
    @Published var selectedPackage = Set<String>()
    @Published var review: ReviewDTO?
    @Published var titleFilter = ""
    @Published var artistFilter = ""
    @Published var albumFilter = ""
    @Published var genreFilter = Set<String>()
    @Published var yearFilter = Set<Int>()
    @Published var playlistFilter = Set<String>()
    @Published var albumTotal = 0
    @Published var trackTotal = 0
    @Published var detailTotal = 0
    @Published var matchTotal = 0
    let strings = Strings()
    private var client: any HelperConnection
    private struct Pending {
        let command: String
        let generation: String
        let token: String?
        let ids: [String]
        let epoch: Int
        let completion: ((ResultDTO) -> Void)?
    }
    private var pending: [String: Pending] = [:]
    private var requestedArtwork = Set<String>()
    private var artworkDemand: [String: Int] = [:]
    private var artworkPending: [String] = []
    private var artworkInFlight = Set<String>()
    private var imageOrder: [String] = []
    private var audioDemand: [String: Int] = [:]
    private var audioPending: [String] = []
    private var audioRequested = Set<String>()
    private var audioRequestID: String?
    private var ignoredAudioRequestID: String?
    private var browserEpoch = 0
    private var albumLoad = 0
    private var trackLoad = 0
    private var detailLoad = 0
    private var preparationID: String?
    private var allTracks: [TrackDTO] = []
    private var allAlbums: [AlbumDTO] = []
    private var musicIDs = Set<String>()
    private var tracksLoaded = false
    private var albumsLoaded = false

    private var dirty = Set<String>()
    private var searchWork: DispatchWorkItem?
    private var monitor: Timer?
    private var unknownWrite = false
    init(client: any HelperConnection = HelperClient()) { self.client = client }
    var busy: Bool { task?.running == true }
    var connected: Bool { !(state?.activeId.isEmpty ?? true) }
    var inspectorEligible: Bool {
        openAlbum == nil && [.library, .incoming].contains(workspace)
    }
    var writable: Bool { ready && connected && state?.writesAllowed == true && !busy && !unknownWrite }
    var t: (String) -> String { strings.text }

    func start() {
        client.onEvent = { [weak self] event in self?.receive(event) }
        client.onExit = { [weak self] status in self?.helperExited(status) }
        do {
            try client.start()
            perform("hello", configure: { _ in }) { [weak self] _ in
                self?.ready = true
                self?.discover(foreground: false)
            }
        } catch { self.error = t("helper.unavailable") + "\n" + String(describing: error) }
        monitor?.invalidate()
        monitor = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.ready, (!self.busy || self.browserPreparing), !self.closing,
                      !self.pending.values.contains(where: { $0.command == "discover" }) else { return }
                self.discover(foreground: false, refreshLibrary: false)
            }
        }
    }

    func perform(_ command: String, foreground: Bool = false,
                 configure: (inout RequestDTO) -> Void = { _ in },
                 completion: @escaping (ResultDTO) -> Void = { _ in }) {
        guard !closing || command == "close" else { return }
        if foreground && busy { return }
        var request = RequestDTO(command, generation: state?.generation ?? "")
        request.revision = state?.revision
        configure(&request)
        if foreground { cancelRequested = false; task = TaskState(id: request.id, command: command) }
        if command == "prepare_browser" { preparationID = request.id }
        pending[request.id] = Pending(command: command, generation: request.generation, token: request.token, ids: request.ids ?? [], epoch: browserEpoch, completion: completion)
        if command == "audio_formats" { audioRequestID = request.id }
        do { try client.send(request) }
        catch {
            pending.removeValue(forKey: request.id)
            if command == "audio_formats" {
                audioRequestID = nil
                for id in request.ids ?? [] { audioFormats[id] = AudioFormatDTO(id: id, detail: String(describing: error)) }
            }
            if foreground { task?.finish(code: "failed", detail: String(describing: error)) }
            self.error = t("helper.unavailable") + "\n" + String(describing: error)
        }
    }

    private func receive(_ envelope: Envelope) {
        if envelope.event == "progress", let progress = envelope.progress {
            if let operation = pending[envelope.id], operation.epoch == browserEpoch {
                task?.receive(id: envelope.id, sequence: envelope.sequence, progress: progress)
            }
            return
        }
        guard let operation = pending.removeValue(forKey: envelope.id) else { return }
        if envelope.id == audioRequestID { audioRequestID = nil }
        let ignoredAudio = envelope.id == ignoredAudioRequestID
        if ignoredAudio { ignoredAudioRequestID = nil }
        let artwork = ["artwork", "preview_artwork"].contains(operation.command)
        if artwork, let token = operation.token {
            let key = operation.command == "preview_artwork" ? "preview:\(token)" : token
            artworkInFlight.remove("\(operation.epoch):\(key)")
        }
        defer {
            if artwork { dispatchArtwork() }
            dispatchAudioFormats()
        }
        guard !ignoredAudio, operation.epoch == browserEpoch else { return }
        let stateCommand = ["hello", "discover", "select", "commit", "delete", "restore", "eject"].contains(operation.command)
        if !stateCommand, let result = envelope.result, result.state.generation != state?.generation { return }
        if let result = envelope.result { apply(result.state) }
        if envelope.event == "error" {
            if operation.command == "audio_formats" {
                for id in operation.ids { audioFormats[id] = AudioFormatDTO(id: id, detail: envelope.detail) }
                return
            }
            if artwork { return }
            if operation.command == "hello" { perform("close") }
            if task?.id == envelope.id { task?.finish(code: envelope.code, detail: envelope.detail) }
            if browserPreparing && ["prepare_browser", "tracks", "albums"].contains(operation.command) {
                clearBrowser()
                task = TaskState(id: envelope.id, command: "prepare_browser")
                task?.finish(code: envelope.code, detail: envelope.detail)
            }
            if envelope.code != "cancelled" { error = envelope.detail }
            if envelope.code == "recovery_required" { workspace = .recovery }
            return
        }
        guard envelope.event == "result", let result = envelope.result else { return }
        if task?.id == envelope.id {
            let warnings = result.warnings ?? []
            if operation.command != "prepare_browser" {
                task?.finish(code: warnings.isEmpty ? "success" : "warning",
                             detail: completionText(operation.command, result: result))
            }
            if !warnings.isEmpty { error = warnings.joined(separator: "\n") }
        }
        operation.completion?(result)
    }

    private func clearBrowser() {
        if let id = preparationID {
            var cancel = RequestDTO("cancel"); cancel.token = id
            try? client.send(cancel)
        }
        preparationID = nil
        browserEpoch += 1
        browserPreparing = false; browserReady = false
        tracksLoaded = false; albumsLoaded = false
        allTracks = []; allAlbums = []; musicIDs = []
        if task?.command == "prepare_browser" { task = nil }
        albums = []; tracks = []; albumTracks = []; matches = []; package = []
        audioFormats = [:]; audioDemand = [:]; audioPending = []; audioRequested = []
        images = [:]; imageOrder = []; requestedArtwork = []; artworkPending = []; artworkDemand = [:]
        selectedTracks = []; selectedMatches = []; selectedPackage = []
        openAlbum = nil; selectedAlbum = nil; review = nil
        albumTotal = 0; trackTotal = 0; detailTotal = 0; matchTotal = 0
        albumLoad += 1; trackLoad += 1; detailLoad += 1
    }

    private func apply(_ new: StateDTO) {
        if let old = state, old.generation != new.generation {
            clearBrowser()
            queue = []; edits = [:]; selectedQueue = nil; dirty = []
            alacOriginalImport = false
        }
        state = new
    }

    private func completionText(_ command: String, result: ResultDTO) -> String {
        switch command {
        case "preview": return String(format: t("prepared.summary"), result.state.queueCount)
        case "commit": return String(format: t("import.summary"), result.count ?? 0)
        case "delete": return String(format: t("removal.summary"), result.count ?? 0)
        case "package_add": return t("package") + " · \(result.state.packageCount)"
        case "restore": return t("restore.summary")
        case "keep": return t("keep.summary")
        default: return t("finished")
        }
    }

    private func helperExited(_ status: Int32) {
        ready = false
        pending.removeAll()
        if closing && !client.running { NSApp.reply(toApplicationShouldTerminate: true); return }
        if busy {
            unknownWrite = ["commit", "delete", "restore"].contains(task?.command ?? "")
            task?.finish(code: unknownWrite ? "unknown" : "failed", detail: t(unknownWrite ? "write.unknown" : "helper.stopped"))
        }
        clearBrowser()
        artworkInFlight = []
        audioRequestID = nil
        ignoredAudioRequestID = nil
        state = nil; queue = []; edits = [:]
        alacOriginalImport = false
        error = t(unknownWrite ? "write.unknown" : "helper.stopped") + " (\(status))"
    }

    func restart() {
        guard !client.running else { return }
        unknownWrite = false; client = HelperClient(); start()
    }

    func requestClose() {
        closing = true; monitor?.invalidate()
        perform("close")
    }

    var helperRunning: Bool { client.running }
    func cancel() {
        if browserPreparing {
            if let id = preparationID {
                var request = RequestDTO("cancel"); request.token = id
                try? client.send(request)
            }
            clearBrowser()
            task?.finish(code: "cancelled", detail: t("cancelled"))
            return
        }
        guard let task, task.running else { return }
        var request = RequestDTO("cancel"); request.token = task.id
        try? client.send(request)
        cancelRequested = true
    }

    func discover(foreground: Bool = true, refreshLibrary: Bool = true) {
        let generation = state?.generation
        perform("discover", foreground: foreground, configure: { $0.source = foreground ? "manual" : "automatic" }) {
            self.devices = $0.devices ?? []
            if let warnings = $0.warnings, !warnings.isEmpty { self.error = warnings.joined(separator: "\n") }
            if self.connected && (refreshLibrary || generation != self.state?.generation) {
                self.refresh()
            }
        }
    }

    func select(_ id: String) {
        guard !busy || browserPreparing else { return }
        clearBrowser()
        task = nil
        perform("select", foreground: true, configure: { $0.token = id }) { _ in self.refresh() }
    }

    func refresh() {
        guard connected else { return }
        if browserReady { applyLibraryFilter(); loadFacets(); filter(); loadPackage(); return }
        guard !browserPreparing, !busy else { return }
        browserPreparing = true
        perform("prepare_browser", foreground: true, configure: { _ in }) { _ in
            self.preparationID = nil
            self.loadAlbums(); self.loadTracks()
            self.loadFacets(); self.filter(); self.loadPackage()
        }
    }

    func searchChanged() {
        searchWork?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.browserReady else { return }
            if self.workspace == .library {
                if self.openAlbum != nil { self.loadDetail() }
                else if self.albumMode { self.loadAlbums() } else { self.loadTracks() }
            }
        }
        searchWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: work)
    }

    func loadAlbums(more: Bool = false) {
        albumLoad += 1
        if browserReady { applyLibraryFilter(); return }
        let load = albumLoad, epoch = browserEpoch, query = ""
        var rows: [AlbumDTO] = []
        func next(_ offset: Int) {
            self.perform("albums", configure: { $0.offset = offset; $0.query = query }) { result in
                guard self.browserEpoch == epoch, self.albumLoad == load else { return }
                let page = result.albums ?? []
                rows += page
                let total = result.total ?? rows.count
                guard self.validBrowserPage(offset: result.offset ?? offset, expected: offset, count: page.count, accumulated: rows.count, total: total) else { return }
                if rows.count < total && !page.isEmpty { next(rows.count) }
                else {
                    self.allAlbums = rows; self.albums = rows; self.albumTotal = total
                    self.albumsLoaded = true; self.finishBrowserPreparation()
                }
            }
        }
        next(0)
    }

    func loadTracks(more: Bool = false) {
        trackLoad += 1
        if browserReady { applyLibraryFilter(); return }
        let load = trackLoad, epoch = browserEpoch, query = ""
        var rows: [TrackDTO] = []
        func next(_ offset: Int) {
            self.perform("tracks", configure: { $0.offset = offset; $0.query = query }) { result in
                guard self.browserEpoch == epoch, self.trackLoad == load else { return }
                let page = result.tracks ?? []
                rows += page
                let total = result.total ?? rows.count
                guard self.validBrowserPage(offset: result.offset ?? offset, expected: offset, count: page.count, accumulated: rows.count, total: total) else { return }
                if self.browserPreparing {
                    var progress = ProgressDTO(phase: "browser.loading", fraction: total > 0 ? Double(rows.count) / Double(total) : 1)
                    progress.completed = rows.count; progress.total = total
                    self.task?.receive(id: self.task?.id ?? "", sequence: rows.count + 1_000_000, progress: progress)
                }
                if rows.count < total && !page.isEmpty { next(rows.count) }
                else {
                    self.allTracks = rows; self.tracks = rows; self.trackTotal = total
                    self.musicIDs = Set(rows.filter { $0.mediaKind == "music" }.map(\.id))
                    self.tracksLoaded = true; self.finishBrowserPreparation()
                }
            }
        }
        next(0)
    }

    private func validBrowserPage(offset: Int, expected: Int, count: Int, accumulated: Int, total: Int) -> Bool {
        guard offset == expected, total >= accumulated, count > 0 || accumulated == total else {
            clearBrowser()
            error = t("browser.incomplete")
            return false
        }
        return true
    }

    private func finishBrowserPreparation() {
        guard browserPreparing, tracksLoaded, albumsLoaded else { return }
        browserPreparing = false; browserReady = true
        applyLibraryFilter()
        if task?.command == "prepare_browser" { task = nil }
        dispatchArtwork(); dispatchAudioFormats()
    }

    func open(_ album: AlbumDTO) {
        selectedAlbum = album; openAlbum = album; loadDetail()
    }

    func selectAlbum(_ album: AlbumDTO) {
        guard browserReady, !busy else { return }
        selectedAlbum = album
        selectedTracks = Set(allTracks.filter { $0.albumId == album.id }.map(\.id)).intersection(musicIDs)
        inspector = true
    }

    func loadDetail(more: Bool = false) { applyLibraryFilter() }

    private func applyLibraryFilter() {
        guard browserReady else { return }
        let needle = query.folding(options: [.caseInsensitive], locale: Locale(identifier: "en_US_POSIX"))
            .split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        let filtered = needle.isEmpty ? allTracks : allTracks.filter { $0.searchable.contains(needle) }
        tracks = filtered; trackTotal = filtered.count
        let albumIDs = Set(filtered.map(\.albumId))
        albums = allAlbums.filter { albumIDs.contains($0.id) }; albumTotal = albums.count
        albumTracks = filtered.filter { $0.albumId == openAlbum?.id }; detailTotal = albumTracks.count
    }

    func replaceVisibleSelection(_ selected: Set<String>, visible: Set<String>) {
        selectedTracks.subtract(visible)
        selectedTracks.formUnion(selected.intersection(visible))
    }

    var selectedMusicCount: Int { selectedTracks.intersection(musicIDs).count }
    func addLibrarySelection() {
        guard browserReady, !busy, selectedMusicCount > 0 else { return }
        addToPackage(selectedTracks.intersection(musicIDs), source: t("library"))
    }

    func audioTrackIDs(for album: AlbumDTO) -> [String] {
        allTracks.filter { $0.albumId == album.id }.map(\.id)
    }

    var audioFormatPlaceholder: String { audioFormatReadingEnabled ? "…" : "—" }

    func setAudioFormatReadingEnabled(_ enabled: Bool) {
        guard !closing, enabled != audioFormatReadingEnabled else { return }
        audioFormatReadingEnabled = enabled
        if enabled {
            audioPending = audioDemand.keys.sorted().filter { audioFormats[$0] == nil && !audioRequested.contains($0) }
            dispatchAudioFormats()
        } else {
            audioPending = []; audioRequested = []
            if let id = audioRequestID {
                ignoredAudioRequestID = id
                var cancel = RequestDTO("cancel"); cancel.token = id
                try? client.send(cancel)
            }
        }
    }

    func acquireAudioFormats(_ ids: [String]) {
        for id in ids {
            audioDemand[id, default: 0] += 1
            if audioFormats[id] == nil && !audioRequested.contains(id) && !audioPending.contains(id) {
                audioPending.append(id)
            }
        }
        dispatchAudioFormats()
    }

    func releaseAudioFormats(_ ids: [String]) {
        for id in ids {
            let remaining = (audioDemand[id] ?? 0) - 1
            if remaining > 0 { audioDemand[id] = remaining }
            else { audioDemand.removeValue(forKey: id); audioPending.removeAll { $0 == id } }
        }
    }

    private func dispatchAudioFormats() {
        guard audioFormatReadingEnabled, ready, connected, browserReady, !busy, !closing, audioRequestID == nil else { return }
        audioPending.removeAll { audioDemand[$0] == nil || audioFormats[$0] != nil || audioRequested.contains($0) }
        let ids = Array(audioPending.prefix(8))
        guard !ids.isEmpty else { return }
        audioPending.removeFirst(ids.count)
        audioRequested.formUnion(ids)
        perform("audio_formats", configure: { $0.ids = ids }) { result in
            let rows = Dictionary((result.audioFormats ?? []).map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
            for id in ids { self.audioFormats[id] = rows[id] ?? AudioFormatDTO(id: id) }
        }
    }

    func artwork(_ id: String, preview: Bool = false) {
        let key = preview ? "preview:\(id)" : id
        guard id != "0", !id.isEmpty else { return }
        artworkDemand[key, default: 0] += 1
        if images[key] == nil, !artworkInFlight.contains("\(browserEpoch):\(key)"), !artworkPending.contains(key) {
            requestedArtwork.remove(key)
        }
        if images[key] == nil, !requestedArtwork.contains(key) {
            requestedArtwork.insert(key); artworkPending.append(key)
        }
        dispatchArtwork()
    }

    func releaseArtwork(_ id: String, preview: Bool = false) {
        let key = preview ? "preview:\(id)" : id
        let remaining = (artworkDemand[key] ?? 0) - 1
        if remaining > 0 { artworkDemand[key] = remaining; return }
        artworkDemand.removeValue(forKey: key)
        if artworkPending.contains(key) {
            artworkPending.removeAll { $0 == key }; requestedArtwork.remove(key)
        }
    }

    func resumeArtwork() { dispatchArtwork() }

    private func dispatchArtwork() {
        guard ready, connected, !busy, !browserPreparing else { return }
        while artworkInFlight.count < 2, !artworkPending.isEmpty {
            let key = artworkPending.removeFirst()
            guard artworkDemand[key] != nil else { requestedArtwork.remove(key); continue }
            let preview = key.hasPrefix("preview:")
            let id = preview ? String(key.dropFirst(8)) : key
            let epoch = browserEpoch
            artworkInFlight.insert("\(epoch):\(key)")
            perform(preview ? "preview_artwork" : "artwork", configure: { $0.token = id }) { result in
                guard epoch == self.browserEpoch else { return }
                if let text = result.image, let data = Data(base64Encoded: text), let image = NSImage(data: data) {
                    self.images[key] = image
                    self.imageOrder.removeAll { $0 == key }; self.imageOrder.append(key)
                    while self.imageOrder.count > 128 {
                        let oldest = self.imageOrder.removeFirst()
                        self.images.removeValue(forKey: oldest); self.requestedArtwork.remove(oldest)
                    }
                }
            }
        }
    }

    func addFiles(folder: Bool) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = folder; panel.canChooseFiles = !folder
        panel.allowsMultipleSelection = true
        panel.begin { [weak self] response in
            guard response == .OK, let self else { return }
            self.prepareImport(paths: panel.urls.map(\.path))
        }
    }

    var canChangeAlacOriginalImport: Bool { ready && !busy && queue.isEmpty && !closing }

    func setAlacOriginalImport(_ enabled: Bool) {
        guard canChangeAlacOriginalImport else { return }
        alacOriginalImport = enabled
    }

    func prepareImport(paths: [String]) {
        guard writable, !paths.isEmpty else { return }
        workspace = .incoming
        let original = alacOriginalImport
        saveEdits {
            self.perform("preview", foreground: true, configure: {
                $0.paths = paths; $0.allowHighResolutionAlac = original
            }) { result in
                self.loadQueue(first: result.preview ?? [], total: result.total ?? 0)
            }
        }
    }

    private func loadQueue(first: [PreviewDTO], total: Int) {
        queue = first
        func next() {
            if self.queue.count >= total { return }
            self.perform("queue", configure: { $0.offset = self.queue.count }) { result in
                let page = result.preview ?? []
                self.queue += page
                if !page.isEmpty { next() }
            }
        }
        next()
    }

    func edit(_ token: String, change: (inout EditDTO) -> Void) {
        guard !busy else { return }
        guard let entry = queue.first(where: { $0.token == token }) else { return }
        var value = edits[token] ?? EditDTO(entry)
        change(&value); edits[token] = value; dirty.insert(token)
    }

    func saveEdits(then completion: @escaping () -> Void) {
        let tokens = Array(dirty.prefix(100))
        guard !tokens.isEmpty else { completion(); return }
        let batch = tokens.compactMap { edits[$0] }
        perform("edit", foreground: true, configure: { $0.edits = batch }) { _ in
            self.dirty.subtract(tokens)
            self.saveEdits(then: completion)
        }
    }

    func importMusic() {
        guard writable, queue.count == state?.queueCount else { return }
        saveEdits {
            self.perform("commit", foreground: true, configure: { $0.ids = self.queue.map(\.token) }) { _ in self.refresh() }
        }
    }

    func cover(clear: Bool) {
        guard let token = selectedQueue else { return }
        let run: ([String]) -> Void = { paths in
            self.saveEdits {
                self.perform(clear ? "clear_cover" : "cover", foreground: true, configure: { $0.ids = [token]; $0.paths = paths }) { _ in
                    self.images.removeValue(forKey: "preview:\(token)")
                    self.requestedArtwork.remove("preview:\(token)")
                    self.artwork(token, preview: true)
                }
            }
        }
        if clear { run([]) }
        else {
            let panel = NSOpenPanel(); panel.allowsMultipleSelection = false
            panel.begin { response in if response == .OK { run(panel.urls.map(\.path)) } }
        }
    }

    func discard() {
        perform("discard", foreground: true, configure: { _ in }) { _ in self.queue = []; self.edits = [:]; self.dirty = [] }
    }

    func loadFacets() {
        perform("facets", configure: { _ in }) { self.genres = $0.genres ?? []; self.years = $0.years ?? []; self.playlists = $0.playlists ?? [] }
    }

    func filter(more: Bool = false) {
        perform("filter", configure: {
            $0.title = self.titleFilter; $0.artist = self.artistFilter; $0.albumFilter = self.albumFilter
            $0.genres = self.genreFilter.map { $0.isEmpty ? nil : $0 }
            $0.years = self.yearFilter.map { $0 == 0 ? nil : $0 }
            $0.playlists = Array(self.playlistFilter); $0.offset = more ? self.matches.count : 0
        }) { result in
            self.matches = (more ? self.matches : []) + (result.tracks ?? [])
            self.matchTotal = result.total ?? 0
        }
    }

    func addToPackage(_ ids: Set<String>, source: String) {
        guard !busy, !ids.isEmpty else { return }
        let sorted = ids.sorted()
        func next(_ offset: Int) {
            let end = min(offset + 1000, sorted.count)
            self.perform("package_add", foreground: true, configure: { $0.ids = Array(sorted[offset..<end]); $0.source = source }) { _ in
                if end < sorted.count { next(end) } else { self.loadPackage() }
            }
        }
        next(0)
    }

    func loadPackage(more: Bool = false) {
        perform("package", configure: { $0.offset = more ? self.package.count : 0 }) { result in
            self.package = (more ? self.package : []) + (result.tracks ?? [])
        }
    }

    func packageAction(clear: Bool) {
        perform(clear ? "package_clear" : "package_remove", configure: { $0.ids = Array(self.selectedPackage) }) { _ in
            self.review = nil; self.selectedPackage = []; self.loadPackage()
        }
    }

    var canReviewRemoval: Bool { writable && (state?.packageCount ?? 0) > 0 }

    func prepareRemoval() {
        guard canReviewRemoval else { return }
        perform("prepare_delete", foreground: true, configure: { _ in }) { self.review = $0.review }
    }

    func confirmRemoval(_ token: String) {
        review = nil
        perform("delete", foreground: true, configure: { $0.token = token }) { _ in self.refresh(); self.workspace = .recovery }
    }

    func restore() {
        perform("restore", foreground: true, configure: { _ in }) { _ in self.refresh() }
    }

    func keepCurrentContents(_ expected: StateDTO) {
        guard ready, !busy, state?.canKeepContents == true,
              state?.generation == expected.generation,
              state?.recoveryPath == expected.recoveryPath,
              !expected.recoveryPath.isEmpty else { return }
        let path = expected.recoveryPath
        perform("keep", foreground: true, configure: { $0.token = path }) { _ in
            self.review = nil
        }
    }

    func eject() { perform("eject", foreground: true) }
}
