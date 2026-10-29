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
    @Published var ready = false
    @Published var closing = false
    @Published var cancelRequested = false
    @Published var error = ""
    @Published var images: [String: NSImage] = [:]
    @Published var query = ""
    @Published var albumMode = true
    @Published var inspector = true
    @Published var selectedAlbum: AlbumDTO?
    @Published var openAlbum: AlbumDTO?
    @Published var selectedTracks = Set<String>()
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
        let completion: ((ResultDTO) -> Void)?
    }
    private var pending: [String: Pending] = [:]
    private var requestedArtwork = Set<String>()
    private var dirty = Set<String>()
    private var searchWork: DispatchWorkItem?
    private var monitor: Timer?
    private var unknownWrite = false
    init(client: any HelperConnection = HelperClient()) { self.client = client }
    var busy: Bool { task?.running == true }
    var connected: Bool { !(state?.activeId.isEmpty ?? true) }
    var writable: Bool { ready && connected && state?.writesAllowed == true && !busy && !unknownWrite }
    var t: (String) -> String { strings.text }

    func start() {
        client.onEvent = { [weak self] event in self?.receive(event) }
        client.onExit = { [weak self] status in self?.helperExited(status) }
        do {
            try client.start()
            perform("hello") { [weak self] _ in
                self?.ready = true
                self?.discover(foreground: false)
            }
        } catch { self.error = t("helper.unavailable") + "\n" + String(describing: error) }
        monitor?.invalidate()
        monitor = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.ready, !self.busy, !self.closing,
                      !self.pending.values.contains(where: { $0.command == "discover" }) else { return }
                self.discover(foreground: false, refreshLibrary: false)
            }
        }
    }

    func perform(_ command: String, foreground: Bool = false, completion: ((ResultDTO) -> Void)? = nil) {
        perform(command, foreground: foreground, configure: { _ in }, completion: completion)
    }

    func perform(_ command: String, foreground: Bool = false,
                 configure: (inout RequestDTO) -> Void,
                 completion: ((ResultDTO) -> Void)? = nil) {
        guard !closing || command == "close" else { return }
        if foreground && busy { return }
        var request = RequestDTO(command, generation: state?.generation ?? "")
        request.revision = state?.revision
        configure(&request)
        if foreground { cancelRequested = false; task = TaskState(id: request.id, command: command) }
        pending[request.id] = Pending(command: command, generation: request.generation, token: request.token, completion: completion)
        do { try client.send(request) }
        catch {
            pending.removeValue(forKey: request.id)
            if foreground { task?.finish(code: "failed", detail: String(describing: error)) }
            self.error = t("helper.unavailable") + "\n" + String(describing: error)
        }
    }

    private func receive(_ envelope: Envelope) {
        if envelope.event == "progress", let progress = envelope.progress {
            task?.receive(id: envelope.id, sequence: envelope.sequence, progress: progress)
            return
        }
        guard let operation = pending.removeValue(forKey: envelope.id) else { return }
        if let result = envelope.result { apply(result.state) }
        if envelope.event == "error" {
            if ["artwork", "preview_artwork"].contains(operation.command), let token = operation.token {
                requestedArtwork.remove(operation.command == "preview_artwork" ? "preview:\(token)" : token)
            }
            if operation.command == "hello" { perform("close") }
            if task?.id == envelope.id { task?.finish(code: envelope.code, detail: envelope.detail) }
            if envelope.code != "cancelled" { error = envelope.detail }
            if envelope.code == "recovery_required" { workspace = .recovery }
            return
        }
        guard envelope.event == "result", let result = envelope.result else { return }
        if task?.id == envelope.id {
            let warnings = result.warnings ?? []
            task?.finish(code: warnings.isEmpty ? "success" : "warning",
                         detail: completionText(operation.command, result: result))
            if !warnings.isEmpty { error = warnings.joined(separator: "\n") }
        }
        operation.completion?(result)
    }

    private func apply(_ new: StateDTO) {
        if let old = state, old.generation != new.generation {
            albums = []; tracks = []; albumTracks = []; queue = []; edits = [:]
            matches = []; package = []; images = [:]; requestedArtwork = []
            selectedTracks = []; selectedMatches = []; selectedPackage = []
            selectedQueue = nil; openAlbum = nil; selectedAlbum = nil; review = nil; dirty = []
            albumTotal = 0; trackTotal = 0; detailTotal = 0; matchTotal = 0
        }
        state = new
    }

    private func completionText(_ command: String, result: ResultDTO) -> String {
        switch command {
        case "preview": return String(format: t("prepared.summary"), result.state.queueCount)
        case "commit": return String(format: t("import.summary"), result.count ?? 0)
        case "delete": return String(format: t("removal.summary"), result.count ?? 0)
        case "restore": return t("restore.summary")
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
        state = nil; queue = []; edits = [:]; albums = []; tracks = []; package = []; review = nil
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
        guard let task, task.running else { return }
        var request = RequestDTO("cancel"); request.token = task.id
        try? client.send(request)
        cancelRequested = true
    }

    func discover(foreground: Bool = true, refreshLibrary: Bool = true) {
        let generation = state?.generation
        perform("discover", foreground: foreground) {
            self.devices = $0.devices ?? []
            if self.connected && (refreshLibrary || generation != self.state?.generation) {
                self.refresh()
            }
        }
    }

    func select(_ id: String) {
        perform("select", foreground: true, configure: { $0.token = id }) { _ in self.refresh() }
    }

    func refresh() {
        guard connected else { return }
        loadAlbums(); loadTracks(); loadFacets(); filter(); loadPackage()
    }

    func searchChanged() {
        searchWork?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            if self.workspace == .library {
                if self.openAlbum != nil { self.loadDetail() }
                else if self.albumMode { self.loadAlbums() } else { self.loadTracks() }
            }
        }
        searchWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: work)
    }

    func loadAlbums(more: Bool = false) {
        let offset = more ? albums.count : 0, query = self.query
        perform("albums", configure: { $0.offset = offset; $0.query = query }) { result in
            guard query == self.query else { return }
            self.albums = (more ? self.albums : []) + (result.albums ?? [])
            self.albumTotal = result.total ?? 0
        }
    }

    func loadTracks(more: Bool = false) {
        let offset = more ? tracks.count : 0, query = self.query
        perform("tracks", configure: { $0.offset = offset; $0.query = query }) { result in
            guard query == self.query else { return }
            self.tracks = (more ? self.tracks : []) + (result.tracks ?? [])
            self.trackTotal = result.total ?? 0
        }
    }

    func open(_ album: AlbumDTO) {
        selectedAlbum = album; openAlbum = album; selectedTracks = []; loadDetail()
    }

    func loadDetail(more: Bool = false) {
        guard let album = openAlbum else { return }
        let offset = more ? albumTracks.count : 0, query = self.query
        perform("tracks", configure: { $0.album = album.id; $0.offset = offset; $0.query = query }) { result in
            guard self.openAlbum?.id == album.id, query == self.query else { return }
            self.albumTracks = (more ? self.albumTracks : []) + (result.tracks ?? [])
            self.detailTotal = result.total ?? 0
        }
    }

    func artwork(_ id: String, preview: Bool = false) {
        let key = preview ? "preview:\(id)" : id
        guard ready, connected, !busy, id != "0", !id.isEmpty,
              images[key] == nil, !requestedArtwork.contains(key) else { return }
        requestedArtwork.insert(key)
        perform(preview ? "preview_artwork" : "artwork", configure: { $0.token = id }) { result in
            self.requestedArtwork.remove(key)
            if let text = result.image, let data = Data(base64Encoded: text), let image = NSImage(data: data) {
                if self.images.count >= 200 { self.images.removeAll() }
                self.images[key] = image
            }
        }
    }

    func addFiles(folder: Bool) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = folder; panel.canChooseFiles = !folder
        panel.allowsMultipleSelection = true
        panel.begin { [weak self] response in
            guard response == .OK, let self else { return }
            self.workspace = .incoming
            self.saveEdits {
                self.perform("preview", foreground: true, configure: { $0.paths = panel.urls.map(\.path) }) { result in
                    self.loadQueue(first: result.preview ?? [], total: result.total ?? 0)
                }
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
        perform("discard", foreground: true) { _ in self.queue = []; self.edits = [:]; self.dirty = [] }
    }

    func loadFacets() {
        perform("facets") { self.genres = $0.genres ?? []; self.years = $0.years ?? []; self.playlists = $0.playlists ?? [] }
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
        perform("package_add", configure: { $0.ids = Array(ids); $0.source = source }) { _ in self.loadPackage() }
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

    func prepareRemoval() {
        perform("prepare_delete", foreground: true) { self.review = $0.review }
    }

    func confirmRemoval(_ token: String) {
        review = nil
        perform("delete", foreground: true, configure: { $0.token = token }) { _ in self.refresh(); self.workspace = .recovery }
    }

    func restore() {
        perform("restore", foreground: true) { _ in self.refresh() }
    }

    func eject() { perform("eject", foreground: true) }
}
