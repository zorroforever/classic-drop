import XCTest
import AppKit
import SwiftUI
import ClassicDropCore
@testable import ClassicDrop

final class WorkspaceLayoutTests: XCTestCase {
    @MainActor
    func testInspectorToggleKeepsNavigationAtLeadingEdgeAndFillsAvailableWidth() async throws {
        guard #available(macOS 14.0, *) else { throw XCTSkip("System Inspector requires macOS 14") }
        let model = AppModel(client: StubConnection())
        try await checkLayout(model)
    }

    @MainActor
    func testConnectedWorkspaceLayoutsFillWindowWithInspectorToggled() async throws {
        guard #available(macOS 14.0, *) else { throw XCTSkip("System Inspector requires macOS 14") }
        for (workspace, grid) in [(Workspace.library, true), (.library, false), (.incoming, false)] {
            let model = try connectedModel()
            model.workspace = workspace
            model.albumMode = grid
            try await checkLayout(model)
        }
    }

    @MainActor
    private func connectedModel() throws -> AppModel {
        let connection = StubConnection()
        let model = AppModel(client: connection)
        model.start()
        try connection.reply("hello")
        try connection.reply("discover")
        try connection.reply("prepare_browser")
        try connection.reply("tracks", extra: #", "tracks":[{"id":"1","title":"Track","artist":"Artist","album":"Album","album_artist":"Artist","album_id":"album","genre":"Pop","year":2020,"track_number":1,"disc_number":1,"length_ms":1000,"size_bytes":100,"artwork_id":"1","source":"iPod"}],"total":1"#)
        try connection.reply("albums", extra: #", "albums":[{"id":"album","title":"Album","artist":"Artist","year":2020,"track_count":1,"duration_ms":1000,"artwork_id":"1"}],"total":1"#)
        return model
    }

    @MainActor
    private func checkLayout(_ model: AppModel) async throws {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 760), styleMask: [.titled, .resizable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        let host = NSHostingView(rootView: WorkspaceView().environmentObject(model).environmentObject(model.strings))
        window.contentView = host; window.orderFront(nil)
        defer { window.contentView = nil; window.close() }
        await settleLayout(host, model: model)
        for width: CGFloat in [1180, 940, 1440] {
            window.setContentSize(NSSize(width: width, height: 760))
            await settleLayout(host, model: model)
            for shown in [true, false, true, false] {
                model.inspector = shown
                await settleLayout(host, model: model)
                let context = "\(model.workspace), grid \(model.albumMode), width \(width), inspector \(shown)"
                XCTAssertEqual(host.bounds.width, width, accuracy: 1)
                XCTAssertEqual(model.inspector, shown, context)
                let splits = verticalSplits(in: host)
                let sidebar = try XCTUnwrap(sidebarTable(in: host))
                var ancestor = sidebar.superview
                while ancestor != nil && !(ancestor is NSSplitView) { ancestor = ancestor?.superview }
                let navigation = try XCTUnwrap(ancestor as? NSSplitView)
                let frame = navigation.convert(navigation.bounds, to: host)
                XCTAssertEqual(frame.minX, 0, accuracy: 1, "Sidebar shifted at width \(width), inspector \(shown)")
                let reserved = shown ? InspectorLayout.maximumInspectorWidth + 1 : 0
                XCTAssertGreaterThanOrEqual(frame.maxX, host.bounds.maxX - reserved - 1)
                XCTAssertLessThanOrEqual(frame.maxX, host.bounds.maxX + 1)
                let inspectorSplit = try XCTUnwrap(splits.first { split in
                    (split.delegate as? NSSplitViewController)?.splitViewItems.contains { $0.behavior == .inspector } == true
                })
                let controller = try XCTUnwrap(inspectorSplit.delegate as? NSSplitViewController)
                let inspector = try XCTUnwrap(controller.splitViewItems.first { $0.behavior == .inspector })
                XCTAssertEqual(inspector.isCollapsed, !shown, context)
                if shown {
                    let inspectorFrame = inspector.viewController.view.convert(inspector.viewController.view.bounds, to: host)
                    XCTAssertEqual(inspectorFrame.maxX, host.bounds.maxX, accuracy: 1, context)
                    XCTAssertGreaterThanOrEqual(inspectorFrame.width, InspectorLayout.minimumInspectorWidth - 1)
                    XCTAssertLessThanOrEqual(inspectorFrame.width, InspectorLayout.maximumInspectorWidth + 1)
                }
                for split in splits {
                    XCTAssertLessThanOrEqual(split.convert(split.bounds, to: host).maxX, host.bounds.maxX + 1)
                }
            }
        }
    }

    private struct LayoutSnapshot: Equatable {
        let width: CGFloat
        let shown: Bool
        let frames: [CGRect]
        let collapsed: [Bool]
    }

    @MainActor
    private func settleLayout(_ host: NSView, model: AppModel) async {
        var previous: LayoutSnapshot?
        var unchanged = 0
        // Inspector animations and native window layout finish asynchronously.
        // Require several equal snapshots; correctness is asserted separately.
        for sample in 0..<50 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            host.layoutSubtreeIfNeeded()
            let splits = verticalSplits(in: host)
            let snapshot = LayoutSnapshot(
                width: host.bounds.width,
                shown: model.inspector,
                frames: splits.flatMap { split in
                    [split.convert(split.bounds, to: host)] + split.arrangedSubviews.map { $0.convert($0.bounds, to: host) }
                },
                collapsed: splits.flatMap { ($0.delegate as? NSSplitViewController)?.splitViewItems.map(\.isCollapsed) ?? [] }
            )
            unchanged = snapshot == previous ? unchanged + 1 : 0
            if sample >= 5 && unchanged >= 3 { return }
            previous = snapshot
        }
        XCTFail("Native split layout did not stabilize")
    }

    @MainActor private func verticalSplits(in view: NSView) -> [NSSplitView] {
        ((view as? NSSplitView).map { $0.isVertical ? [$0] : [] } ?? []) + view.subviews.flatMap { verticalSplits(in: $0) }
    }

    @MainActor private func sidebarTable(in view: NSView) -> NSTableView? {
        if let table = view as? NSTableView { return table }
        return view.subviews.lazy.compactMap { self.sidebarTable(in: $0) }.first
    }
}
