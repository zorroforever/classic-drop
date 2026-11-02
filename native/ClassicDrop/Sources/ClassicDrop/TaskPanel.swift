import SwiftUI
import ClassicDropCore

struct TaskProgressText {
    let title: String
    let item: String
    let details: String

    init(_ progress: ProgressDTO, strings: Strings) {
        let translated = strings.text(progress.phase)
        title = translated == progress.phase ? strings.text("task.start") : translated
        // Database preparation uses its stage description as the current item.
        // File names and other user data must remain unchanged.
        item = progress.phase.hasPrefix("database.") && progress.unit == "steps"
            && progress.currentItem == progress.message ? title : progress.currentItem
        var lines = [title]
        if !item.isEmpty && item != title { lines.append(item) }
        if let completed = progress.completed {
            lines.append(progress.total.map { "\(completed) / \($0)" } ?? "\(completed)")
        }
        details = lines.joined(separator: "\n")
    }
}

struct TaskPanel: View {
    @EnvironmentObject var model: AppModel
    @EnvironmentObject var strings: Strings
    @State private var details = false
    private func t(_ key: String) -> String { strings.text(key) }
    private var title: String {
        guard let task = model.task else { return t("task.idle") }
        if !task.running {
            if task.outcome == "success" { return task.detail }
            if task.outcome == "warning" { return t("warning") }
            if task.outcome == "cancelled" { return t("cancelled") }
            if task.outcome == "unknown" { return t("write.unknown") }
            return t("failed")
        }
        if let progress = task.progress {
            return TaskProgressText(progress, strings: strings).title
        }
        return t("operation." + task.command)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if model.closing { Text(t("task.closing")).font(.callout).foregroundStyle(.secondary) }
            if let task = model.task {
                GroupBox {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(alignment: .top, spacing: 18) {
                            VStack(alignment: .leading, spacing: 5) {
                                Text(title).font(.headline).fixedSize(horizontal: false, vertical: true)
                                if task.running, let progress = task.progress {
                                    HStack(spacing: 10) {
                                        let item = TaskProgressText(progress, strings: strings).item
                                        if !item.isEmpty { Text(item).lineLimit(1).truncationMode(.middle) }
                                        if let completed = progress.completed {
                                            Text(progress.total.map { "\(completed) / \($0)" } ?? "\(completed)")
                                        }
                                        if let fraction = progress.fraction {
                                            Text(t(progress.measurement == "current_file" ? "task.file" : "task.stage") + " " + fraction.formatted(.percent.precision(.fractionLength(0))))
                                                .foregroundStyle(Color.accentColor)
                                        }
                                    }.font(.caption).foregroundStyle(.secondary)
                                } else if !task.detail.isEmpty && task.outcome != "success" {
                                    Text(task.detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                }
                                if task.running && task.command == "preview" { Text(t("queue.ready")).font(.caption).foregroundStyle(.secondary) }
                            }
                            Spacer(minLength: 0)
                            if task.running {
                                TimelineView(.periodic(from: task.started, by: 1)) { context in
                                    Text(String(format: t("task.elapsed"), durationText(Int(context.date.timeIntervalSince(task.started) * 1000))))
                                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                                }
                                Button(t(model.cancelRequested ? "cancelling" : "cancel")) { model.cancel() }.disabled(model.closing || model.cancelRequested)
                            } else {
                                Button { model.task = nil } label: { Image(systemName: "xmark") }
                                    .buttonStyle(.borderless).help(t("close"))
                            }
                        }
                        if task.running {
                            Group {
                                if let fraction = task.progress?.fraction { ProgressView(value: fraction) }
                                else { ProgressView() }
                            }
                            .progressViewStyle(.linear).scaleEffect(x: 1, y: 1.5).frame(height: 10)
                            .accessibilityLabel(title)
                        }
                        DisclosureGroup(t("task.details"), isExpanded: $details) {
                            Text(task.running ? task.progress.map { TaskProgressText($0, strings: strings).details } ?? title : task.detail).font(.caption).textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }.font(.caption)
                    }
                }
            }
            HStack {
                if model.state?.writesAllowed == false && model.state?.canRestore == true {
                    Label(t("recovery.blocked"), systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(.secondary)
                } else if model.workspace == .incoming {
                    Text(t("queue.ready")).font(.caption).foregroundStyle(.secondary)
                } else if model.task == nil {
                    Text(t("task.idle")).font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 4)
                if model.workspace == .incoming {
                    Button(t(model.playlistSupported ? (model.playlistDraft?.dirty == true ? "playlist.check.combined" : "playlist.check.import") : "import.action")) { model.importMusic() }
                        .buttonStyle(.borderedProminent)
                        .disabled(!model.writable || model.queue.isEmpty || model.queue.count != model.state?.queueCount)
                } else if model.workspace == .removal {
                    Button(t("package.review")) { model.prepareRemoval() }
                        .disabled(!model.writable || (model.state?.packageCount ?? 0) == 0)
                }
            }
        }.padding(.horizontal, 20).padding(.vertical, model.task == nil ? 12 : 14)
    }
}
