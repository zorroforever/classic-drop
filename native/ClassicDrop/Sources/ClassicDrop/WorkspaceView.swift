import SwiftUI
import AppKit
import ClassicDropCore

struct WorkspaceView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @State private var sidebar = true
    private func t(_ key: String) -> String { strings.text(key) }

    var body: some View {
        GeometryReader { geometry in
            HSplitView {
                if sidebar { SidebarView().frame(minWidth: 180, idealWidth: 210, maxWidth: 250) }
                VStack(spacing: 0) {
                    HStack(spacing: 0) {
                        content.frame(maxWidth: .infinity, maxHeight: .infinity)
                        if model.inspector && model.openAlbum == nil && [.library, .incoming].contains(model.workspace) {
                            Divider()
                            InspectorView().frame(width: geometry.size.width < 1100 ? 235 : 270)
                        }
                    }
                    Divider()
                    TaskPanel()
                }
                .frame(minWidth: 660)
                .background(Color(nsColor: .textBackgroundColor))
            }
            .onAppear { if geometry.size.width < 1100 { model.inspector = false } }
        }
        .frame(minWidth: 940, minHeight: 580)
        .background(WindowSetup())
        .toolbar {
            ToolbarItem(placement: .navigation) {
                Button { sidebar.toggle() } label: { Image(systemName: "sidebar.left") }
                    .help(t("library.section"))
            }
            ToolbarItem(placement: .principal) {
                HStack(spacing: 14) {
                    Text(t(model.workspace.rawValue)).font(.headline)
                    if model.workspace == .library {
                        TextField(t("search"), text: $model.query)
                            .textFieldStyle(.roundedBorder).frame(minWidth: 170, idealWidth: 260, maxWidth: 340)
                            .onChange(of: model.query) { _ in model.searchChanged() }
                    }
                }
            }
            ToolbarItemGroup(placement: .automatic) {
                if model.workspace == .library {
                    Picker(t("songs"), selection: $model.albumMode) {
                        Image(systemName: "list.bullet").tag(false)
                        Image(systemName: "square.grid.2x2").tag(true)
                    }
                    .pickerStyle(.segmented).frame(width: 82)
                    .onChange(of: model.albumMode) { _ in model.openAlbum = nil; model.searchChanged() }
                    Button { model.inspector.toggle() } label: { Image(systemName: "sidebar.right") }
                        .help(t("inspector"))
                }
                Menu {
                    Button(t("add.files")) { model.addFiles(folder: false) }
                    Button(t("add.folder")) { model.addFiles(folder: true) }
                } label: { Image(systemName: "plus") }
                .disabled(!model.writable)
                Menu {
                    Button(t("refresh")) { model.discover() }.disabled(model.busy)
                    Menu(t("language")) {
                        Picker(t("language"), selection: $strings.language) {
                            Text(t("system")).tag("system")
                            Text("简体中文").tag("zh-Hans")
                            Text("English").tag("en")
                            Text("日本語").tag("ja")
                        }
                    }
                    if !model.ready { Button(t("restart")) { model.restart() } }
                } label: { Image(systemName: "ellipsis") }
            }
        }
        .sheet(item: $model.review) { RemovalReviewView(review: $0) }
        .sheet(isPresented: Binding(get: { !model.error.isEmpty }, set: { if !$0 { model.error = "" } })) {
            VStack(alignment: .leading, spacing: 18) {
                Label(t("details"), systemImage: "exclamationmark.triangle").font(.title2)
                ScrollView { Text(model.error).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                HStack { Spacer(); Button(t("close")) { model.error = "" }.keyboardShortcut(.defaultAction) }
            }.padding(24).frame(width: 580, height: 330)
        }
    }

    @ViewBuilder private var content: some View {
        if !model.connected && model.workspace != .recovery {
            EmptyWorkspace(symbol: "ipod", title: t("device.none"), detail: t("device.hint")) {
                Button(t("refresh")) { model.discover() }.disabled(model.busy || !model.ready)
            }
        } else {
            switch model.workspace {
            case .library: LibraryView()
            case .incoming: ImportView()
            case .removal: RemovalView()
            case .recovery: RecoveryView()
            }
        }
    }
}

struct SidebarView: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    var body: some View {
        VStack(spacing: 0) {
            List(selection: Binding<Workspace?>(get: { model.workspace }, set: { if let value = $0 { model.workspace = value } })) {
                Section(strings.text("library.section")) {
                    ForEach(Workspace.allCases) { workspace in
                        HStack {
                            Label(strings.text(workspace.rawValue), systemImage: workspace.symbol)
                            Spacer()
                            let count = workspace == .incoming ? model.state?.queueCount : workspace == .removal ? model.state?.packageCount : nil
                            if let count, count > 0 { Text(count.formatted()).font(.caption).foregroundStyle(.secondary) }
                        }.tag(workspace).padding(.vertical, 5)
                    }
                }
            }
            .listStyle(.sidebar)
            .onChange(of: model.workspace) { workspace in
                if model.connected && workspace == .removal { model.filter(); model.loadPackage() }
            }
            VStack(alignment: .leading, spacing: 12) {
                Divider()
                Text(strings.text("device.section")).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                if let state = model.state, !state.activeId.isEmpty {
                    HStack {
                        Image(systemName: "ipod").font(.title2).foregroundStyle(.secondary)
                        Text(state.activeName).font(.headline).lineLimit(2)
                        Spacer(minLength: 0)
                        Button { model.eject() } label: { Image(systemName: "eject") }
                            .buttonStyle(.borderless).disabled(model.busy).help(strings.text("eject"))
                    }
                    if state.totalBytes > 0 {
                        ProgressView(value: Double(max(0, state.totalBytes - state.availableBytes)), total: Double(state.totalBytes))
                    }
                    Text(String(format: strings.text("available"), ByteCountFormatter.string(fromByteCount: state.availableBytes, countStyle: .file)))
                        .font(.caption).foregroundStyle(.secondary)
                }
                Menu {
                    ForEach(model.devices) { device in
                        Button(device.name + " · " + device.detail) { model.select(device.id) }.disabled(!device.selectable || model.busy)
                    }
                    Divider()
                    Button(strings.text("refresh")) { model.discover() }.disabled(model.busy || !model.ready)
                } label: { Label(strings.text("device.choose"), systemImage: "cable.connector") }
                .disabled(!model.ready)
            }.padding(18)
        }.frame(maxHeight: .infinity)
    }
}

struct EmptyWorkspace<Action: View>: View {
    let symbol, title, detail: String
    @ViewBuilder var action: () -> Action
    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: symbol).font(.system(size: 48, weight: .light)).foregroundStyle(.secondary)
            Text(title).font(.title2.weight(.semibold))
            Text(detail).foregroundStyle(.secondary).multilineTextAlignment(.center).frame(maxWidth: 400)
            action()
        }.padding(30).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct CoverView: View {
    @EnvironmentObject var model: AppModel
    var id: String
    var preview = false
    var radius: CGFloat = 12
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: radius).fill(Color(nsColor: .quaternaryLabelColor).opacity(0.25))
            if let image = model.images[preview ? "preview:\(id)" : id] {
                Image(nsImage: image).resizable().scaledToFit()
            } else {
                Image(systemName: "music.note").font(.system(size: 42, weight: .light)).foregroundStyle(.tertiary)
            }
        }
        .aspectRatio(1, contentMode: .fit).clipShape(RoundedRectangle(cornerRadius: radius))
        .accessibilityHidden(true)
        .onAppear { model.artwork(id, preview: preview) }
        .onChange(of: id) { _ in model.artwork(id, preview: preview) }
        .onChange(of: model.busy) { busy in if !busy { model.artwork(id, preview: preview) } }
    }
}

struct WindowSetup: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            window.title = "Classic Drop"
            window.titlebarAppearsTransparent = true
            window.toolbarStyle = .unified
            window.setContentSize(NSSize(width: 1180, height: 760))
            window.contentMinSize = NSSize(width: 940, height: 580)
        }
        return view
    }
    func updateNSView(_ view: NSView, context: Context) {}
}
