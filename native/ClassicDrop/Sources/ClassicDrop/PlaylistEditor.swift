import SwiftUI
import ClassicDropCore

struct PlaylistEditor: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @Environment(\.dismiss) private var dismiss
    let context: PlaylistEditorState
    @State private var name = ""
    @State private var description = ""
    @State private var parent = ""
    @State private var smart = SmartPlaylistDTO()
    @State private var initialized = false
    private func t(_ key: String) -> String { strings.text(key) }
    private var duplicate: Bool { model.playlistItems.contains { $0.id != context.playlist?.id && $0.name == name.trimmingCharacters(in: .whitespacesAndNewlines) } }
    private var supportsRules: Bool { context.playlist == nil || context.playlist?.canEditRules == true && context.playlist?.smart?.editable != false }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(t(context.moveOnly ? "playlist.move" : context.playlist == nil ? "playlist.new" : "playlist.edit")).font(.title2.bold())
            if !context.moveOnly {
                TextField(t("playlist.name"), text: $name).textFieldStyle(.roundedBorder)
                TextField(t("playlist.description"), text: $description).textFieldStyle(.roundedBorder)
            }
            if context.playlist == nil || context.moveOnly {
                Picker(t("playlist.parent"), selection: $parent) {
                    Text(t("playlist.root")).tag("")
                    ForEach(model.playlistItems.filter { $0.kind == "folder" && $0.id != context.playlist?.id }) { item in Text(item.fullPath).tag(item.id) }
                }
            }
            if duplicate && !context.moveOnly { Label(t("playlist.same.name"), systemImage: "info.circle").font(.caption).foregroundStyle(.orange) }
            if context.kind == "smart" && !context.moveOnly {
                if supportsRules { smartEditor }
                else { Label(t("playlist.unsupported"), systemImage: "lock"); Text(smart.supportReason).textSelection(.enabled) }
            }
            Spacer(minLength: 0)
            PlaylistInlineError()
            if model.smartPreviewRunning {
                HStack {
                    ProgressView().controlSize(.small)
                    Text(t(model.cancelRequested ? "cancelling" : "playlist.preview.running")).font(.callout).foregroundStyle(.secondary)
                }
            }
            GlassControls {
                HStack {
                    if model.smartPreviewRunning {
                        Button(t(model.cancelRequested ? "cancelling" : "playlist.preview.cancel")) { model.cancelSmartPreview() }
                            .keyboardShortcut(.cancelAction).disabled(model.cancelRequested)
                    } else {
                        Button(t("cancel")) { model.smartPreviewEpoch += 1; dismiss() }.keyboardShortcut(.cancelAction).disabled(model.busy)
                    }
                    Spacer()
                    if context.kind == "smart", supportsRules, !context.moveOnly {
                        Button(t("playlist.preview")) { model.previewSmart(smart, playlistId: context.playlist?.id) }.disabled(!model.playlistEditable)
                    }
                    Button(t(context.kind == "smart" && supportsRules && !context.moveOnly ? "playlist.rules.apply" : "playlist.apply")) { apply() }
                        .keyboardShortcut(.defaultAction).disabled(!model.playlistEditable || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }.padding(24).frame(width: 720, height: context.kind == "smart" && !context.moveOnly ? 720 : 310)
        .onAppear {
            guard !initialized else { return }; initialized = true
            name = context.playlist?.name ?? ""; description = context.playlist?.description ?? ""
            parent = context.parentId ?? ""; smart = context.playlist?.smart ?? SmartPlaylistDTO()
            if context.playlist == nil, context.kind == "smart", let field = model.smartFields.first { smart.rules.rules = [field.defaultRule] }
            model.smartPreview = []; model.smartPreviewTotal = 0; model.smartPreviewCalculated = false
        }
        .onChange(of: smart) { _ in model.smartPreviewEpoch += 1; model.smartPreview = []; model.smartPreviewTotal = 0; model.smartPreviewCalculated = false }
        .interactiveDismissDisabled(model.busy)
    }
    private var smartEditor: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Toggle(t("playlist.match.rules"), isOn: $smart.matchRules)
                SmartGroupEditor(node: $smart.rules)
                Toggle(t("playlist.live"), isOn: $smart.liveUpdate)
                Text(t("playlist.live.hint")).font(.caption).foregroundStyle(.secondary)
                Toggle(t("playlist.checked"), isOn: $smart.checkedOnly)
                Toggle(t("playlist.limit"), isOn: Binding(get: { smart.limit != nil }, set: { smart.limit = $0 ? SmartLimitDTO() : nil }))
                if smart.limit != nil {
                    HStack {
                        TextField(t("playlist.limit.value"), text: Binding(get: { String(smart.limit?.value ?? 50) }, set: { smart.limit?.value = Int($0) ?? -1 })).frame(width: 70)
                        Picker(t("playlist.limit.unit"), selection: Binding(get: { smart.limit?.unit ?? "tracks" }, set: { smart.limit?.unit = $0 })) {
                            ForEach(["tracks", "minutes", "hours", "megabytes", "gigabytes"], id: \.self) { Text(t("playlist.unit." + $0)).tag($0) }
                        }
                        Picker(t("playlist.limit.sort"), selection: Binding(get: { smart.limit?.sort ?? "random" }, set: { smart.limit?.sort = $0 })) {
                            ForEach(["random", "title", "album", "artist", "genre", "date_added", "play_count", "last_played", "rating"], id: \.self) { Text(t("playlist.field." + $0)).tag($0) }
                        }
                    }
                    Toggle(t("playlist.descending"), isOn: Binding(get: { smart.limit?.descending ?? false }, set: { smart.limit?.descending = $0 }))
                }
                if model.smartPreviewCalculated {
                    Text(String(format: t("playlist.preview.count"), model.smartPreviewTotal, durationText(model.smartPreview.reduce(0) { $0 + $1.lengthMs }))).font(.headline)
                    ForEach(model.smartPreview) { track in HStack { Text(track.title); Spacer(); Text(track.artist).foregroundStyle(.secondary) } }
                }
            }.padding(8)
        }
    }
    private func apply() {
        let id = context.playlist?.id
        if context.moveOnly {
            var edit = PlaylistEditDTO(action: "move", playlistId: id); edit.parentId = parent.isEmpty ? nil : parent
            model.mutatePlaylist(edit) { dismiss() }; return
        }
        var edit = PlaylistEditDTO(action: id == nil ? "create" : "update", playlistId: id)
        edit.name = name.trimmingCharacters(in: .whitespacesAndNewlines); edit.description = description; edit.kind = context.kind
        if context.kind == "smart", supportsRules { edit.smart = smart }
        if id == nil { edit.parentId = parent.isEmpty ? nil : parent }
        model.mutatePlaylist(edit) { dismiss() }
    }
}

struct SmartGroupEditor: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @Binding var node: SmartNodeDTO
    private func t(_ key: String) -> String { strings.text(key) }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Picker(t("playlist.match"), selection: Binding(get: { node.match ?? "all" }, set: { node.match = $0 })) {
                    Text(t("playlist.match.all")).tag("all"); Text(t("playlist.match.any")).tag("any")
                }.frame(width: 190)
                Spacer()
                Button(t("playlist.rule.add")) { if let field = model.smartFields.first { node.rules = (node.rules ?? []) + [field.defaultRule] } }
                Button(t("playlist.group.add")) { node.rules = (node.rules ?? []) + [SmartNodeDTO()] }
            }
            ForEach(Array((node.rules ?? []).indices), id: \.self) { index in
                HStack(alignment: .top) {
                    if node.rules?[index].kind == "group" {
                        AnyView(SmartGroupEditor(node: child(index))).padding(.leading, 12)
                    } else { SmartRuleEditor(node: child(index)) }
                    Button { guard node.rules?.indices.contains(index) == true else { return }; node.rules?.remove(at: index) } label: { Image(systemName: "minus.circle") }.buttonStyle(.borderless).help(t("playlist.rule.remove"))
                }
            }
        }.padding(10).overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.25)))
    }
    private func child(_ index: Int) -> Binding<SmartNodeDTO> {
        Binding(get: { node.rules?.indices.contains(index) == true ? node.rules![index] : SmartNodeDTO() },
                set: { if node.rules?.indices.contains(index) == true { node.rules?[index] = $0 } })
    }
}
struct SmartRuleEditor: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @Binding var node: SmartNodeDTO
    private var field: SmartFieldDTO? { model.smartFields.first { $0.field == node.field } }
    private func t(_ key: String) -> String { strings.text(key) }
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            if node.kind == "unsupported" { Text(node.description ?? t("playlist.unsupported")) }
            else {
                HStack {
                    Picker(t("playlist.field"), selection: Binding(get: { node.field ?? "" }, set: { selected in if let field = model.smartFields.first(where: { $0.field == selected }) { node = field.defaultRule } })) {
                        ForEach(model.smartFields) { Text(t("playlist.field." + $0.field)).tag($0.field) }
                    }
                    Picker(t("playlist.operator"), selection: Binding(get: { node.operator ?? "" }, set: { node.operator = $0; node.upperValue = $0 == "between" ? node.value : nil })) {
                        ForEach(field?.operators ?? [], id: \.self) { Text(t("playlist.operator." + $0)).tag($0) }
                    }
                }
                valueEditor(upper: false)
                if node.operator == "between" { valueEditor(upper: true) }
                if ["in_last", "not_in_last"].contains(node.operator ?? "") { Text(t("playlist.relative.seconds")).font(.caption).foregroundStyle(.secondary) }
            }
        }
    }
    @ViewBuilder private func valueEditor(upper: Bool) -> some View {
        if field?.valueKind == "playlist" {
            Picker(t("playlist.value"), selection: scalarText(upper)) {
                Text(t("playlist.choose")).tag("")
                ForEach(model.playlistItems.filter { $0.id != model.playlistEditor?.playlist?.id }) { Text($0.fullPath).tag($0.id) }
            }
        } else if field?.valueKind == "choice" {
            Picker(t("playlist.value"), selection: scalarText(upper)) {
                ForEach(field?.choices ?? []) { Text(t("playlist.choice." + $0.value)).tag($0.value) }
            }
        } else if field?.valueKind == "boolean" {
            EmptyView()
        } else if field?.valueKind == "date", !["in_last", "not_in_last"].contains(node.operator ?? "") {
            DatePicker(t(upper ? "playlist.value.upper" : "playlist.value"), selection: Binding(get: {
                Date(timeIntervalSince1970: Double(scalarText(upper).wrappedValue) ?? Date().timeIntervalSince1970)
            }, set: { scalarText(upper).wrappedValue = String(Int64($0.timeIntervalSince1970)) }), displayedComponents: [.date])
        } else {
            TextField(t(upper ? "playlist.value.upper" : "playlist.value"), text: scalarText(upper)).textFieldStyle(.roundedBorder)
        }
    }
    private func scalarText(_ upper: Bool) -> Binding<String> {
        Binding(get: { (upper ? node.upperValue : node.value)?.value.text ?? "" }, set: { text in
            let kind = field?.valueKind ?? "text"
            let scalar: SmartScalar = ["text", "choice", "playlist"].contains(kind) ? .text(text) : Int64(text).map(SmartScalar.integer) ?? .text(text)
            let value = SmartValueDTO(kind: kind, value: scalar)
            if upper { node.upperValue = value } else { node.value = value }
        })
    }
}

struct PlaylistAddTracks: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @Environment(\.dismiss) private var dismiss
    @State private var selection: [String] = []
    @State private var search = ""
    @State private var allowRepeat = false
    private var visibleTracks: [TrackDTO] {
        model.playlistAvailableTracks.filter { search.isEmpty || $0.searchable.localizedCaseInsensitiveContains(search) }
    }
    private var visibleSelection: Binding<Set<String>> {
        let visible = visibleTracks.map(\.id)
        let visibleIDs = Set(visible)
        return Binding(get: { Set(selection).intersection(visibleIDs) }, set: { selected in
            selection.removeAll { visibleIDs.contains($0) && !selected.contains($0) }
            let existing = Set(selection)
            selection.append(contentsOf: visible.filter { selected.contains($0) && !existing.contains($0) })
        })
    }
    private var pendingTracks: [TrackDTO] {
        let tracks = Dictionary(uniqueKeysWithValues: model.playlistAvailableTracks.map { ($0.id, $0) })
        return selection.compactMap { tracks[$0] }
    }
    private func selected(_ id: String) -> Binding<Bool> {
        Binding(get: { selection.contains(id) }, set: { selected in
            if selected {
                if !selection.contains(id) { selection.append(id) }
            } else {
                selection.removeAll { $0 == id }
            }
        })
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(strings.text("playlist.add")).font(.title2.bold())
            TextField(strings.text("search"), text: $search).textFieldStyle(.roundedBorder)
            HStack(alignment: .top, spacing: 16) {
                Table(visibleTracks, selection: visibleSelection) {
                    TableColumn(strings.text("playlist.pick")) { track in
                        Toggle(track.title, isOn: selected(track.id)).labelsHidden().toggleStyle(.checkbox)
                            .accessibilityLabel(strings.text("playlist.pick") + " " + track.title)
                            .accessibilityIdentifier("playlist.pick.\(track.id)")
                    }.width(42)
                    TableColumn(strings.text("title"), value: \.title)
                    TableColumn(strings.text("artist"), value: \.artist)
                    TableColumn(strings.text("album"), value: \.album)
                }
                GroupBox {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(strings.text("playlist.pending.hint")).font(.caption).foregroundStyle(.secondary)
                        if selection.isEmpty {
                            Text(strings.text("playlist.pending.empty")).foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, maxHeight: .infinity)
                        } else {
                            ScrollView {
                                LazyVStack(spacing: 0) {
                                    ForEach(Array(pendingTracks.enumerated()), id: \.element.id) { index, track in
                                        HStack(spacing: 8) {
                                            Text("\(index + 1)").monospacedDigit().foregroundStyle(.secondary).frame(minWidth: 22)
                                            VStack(alignment: .leading, spacing: 2) {
                                                Text(track.title).lineLimit(1)
                                                Text(track.artist + " · " + track.album).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                            }.frame(maxWidth: .infinity, alignment: .leading)
                                            Button { selection.removeAll { $0 == track.id } } label: { Image(systemName: "xmark.circle.fill") }
                                                .buttonStyle(.borderless)
                                                .help(strings.text("playlist.pending.remove"))
                                                .accessibilityLabel(strings.text("playlist.pending.remove") + " " + track.title)
                                                .accessibilityIdentifier("playlist.pending.remove.\(track.id)")
                                        }.padding(.vertical, 6)
                                        Divider()
                                    }
                                }
                            }
                        }
                    }.frame(maxHeight: .infinity)
                } label: {
                    Text(String(format: strings.text("playlist.pending.count"), selection.count))
                }.frame(width: 280)
            }.disabled(model.busy)
            HStack {
                Text(String(format: strings.text("selection.count"), selection.count)).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button(strings.text("selection.clear")) { selection = [] }.disabled(selection.isEmpty)
            }
            PlaylistInlineError()
            Toggle(strings.text("playlist.repeat"), isOn: $allowRepeat)
            HStack {
                Button(strings.text("cancel")) { dismiss() }.keyboardShortcut(.cancelAction)
                Spacer()
                Button(strings.text("playlist.add")) {
                    var edit = PlaylistEditDTO(action: "append", playlistId: model.selectedPlaylist)
                    edit.trackIds = selection; edit.allowRepeat = allowRepeat
                    model.mutatePlaylist(edit) { dismiss() }
                }.disabled(selection.isEmpty || !model.playlistEditable).keyboardShortcut(.defaultAction)
            }
        }.padding(24).frame(width: 940, height: 600).interactiveDismissDisabled(model.busy)
    }
}

struct PlaylistTrackTargets: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @Environment(\.dismiss) private var dismiss
    @State private var targets = Set<String>()
    @State private var allowRepeat = false
    @State private var newName = ""
    @State private var parent = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(strings.text("playlist.targets")).font(.title2.bold())
            Text(strings.text("playlist.targets.hint")).font(.caption).foregroundStyle(.secondary)
            List(model.playlistItems.filter(\.canEditEntries)) { item in
                Toggle(item.fullPath, isOn: Binding(get: { targets.contains(item.id) }, set: { if $0 { targets.insert(item.id) } else { targets.remove(item.id) } }))
            }
            TextField(strings.text("playlist.import.new"), text: $newName).textFieldStyle(.roundedBorder)
            Picker(strings.text("playlist.parent"), selection: $parent) {
                Text(strings.text("playlist.root")).tag("")
                ForEach(model.playlistItems.filter { $0.kind == "folder" }) { Text($0.fullPath).tag($0.id) }
            }
            PlaylistInlineError()
            Toggle(strings.text("playlist.repeat"), isOn: $allowRepeat)
            HStack {
                Button(strings.text("cancel")) { dismiss() }.keyboardShortcut(.cancelAction)
                Spacer()
                Button(strings.text("playlist.apply")) { apply() }.disabled(!model.playlistEditable || targets.isEmpty && newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty).keyboardShortcut(.defaultAction)
            }
        }.padding(24).frame(width: 640, height: 500).interactiveDismissDisabled(model.busy)
    }
    private func apply() {
        let ids = model.playlistAvailableTracks.filter { model.selectedTracks.contains($0.id) }.map(\.id)
        let ordered = targets.sorted()
        @MainActor func next(_ index: Int) {
            if index == ordered.count {
                if !newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    var edit = PlaylistEditDTO(action: "create"); edit.kind = "playlist"
                    edit.name = newName.trimmingCharacters(in: .whitespacesAndNewlines); edit.parentId = parent.isEmpty ? nil : parent
                    edit.trackIds = ids; edit.allowRepeat = allowRepeat
                    model.mutatePlaylist(edit) { dismiss() }
                } else { dismiss() }; return
            }
            var edit = PlaylistEditDTO(action: "append", playlistId: ordered[index]); edit.trackIds = ids; edit.allowRepeat = allowRepeat
            model.mutatePlaylist(edit) { next(index + 1) }
        }
        next(0)
    }
}
