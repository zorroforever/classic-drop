import SwiftUI
import AppKit

@main
struct ClassicDropApp: App {
    @StateObject private var model = AppModel()
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    var body: some Scene {
        WindowGroup {
            WorkspaceView().environmentObject(model).environmentObject(model.strings)
                .onAppear { delegate.model = model; if !model.helperRunning { model.start() } }
        }
        .windowToolbarStyle(.unified)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button(model.t("add.files")) { model.addFiles(folder: false) }.keyboardShortcut("o").disabled(!model.writable)
                Button(model.t("add.folder")) { model.addFiles(folder: true) }.keyboardShortcut("o", modifiers: [.command, .shift]).disabled(!model.writable)
            }
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var model: AppModel?
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model, model.helperRunning else { return .terminateNow }
        model.requestClose()
        return .terminateLater
    }
}
