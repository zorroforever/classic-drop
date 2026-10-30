import Foundation
import ClassicDropCore

protocol HelperConnection: AnyObject {
    var onEvent: ((Envelope) -> Void)? { get set }
    var onExit: ((Int32) -> Void)? { get set }
    var running: Bool { get }
    func start() throws
    func send(_ command: RequestDTO) throws
}

final class HelperClient: HelperConnection {
    var onEvent: ((Envelope) -> Void)?
    var onExit: ((Int32) -> Void)?
    private var process: Process?
    private var input: FileHandle?
    private let reader = DispatchQueue(label: "classic-drop.protocol")
    private let writer = DispatchQueue(label: "classic-drop.commands")
    private var lines = LineDecoder()
    var running: Bool { process?.isRunning == true }

    func start() throws {
        guard process == nil else { throw WireError.unavailable }
        let child = Process()
        let bundled = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/ClassicDropHelper.app/Contents/MacOS/classic-drop-helper")
        if FileManager.default.isExecutableFile(atPath: bundled.path) {
            child.executableURL = bundled
        } else if let executable = ProcessInfo.processInfo.environment["CLASSIC_DROP_HELPER"] {
            child.executableURL = URL(fileURLWithPath: executable)
        } else if let python = ProcessInfo.processInfo.environment["CLASSIC_DROP_PYTHON"] {
            child.executableURL = URL(fileURLWithPath: python)
            child.arguments = ["-m", "classic_drop.native_helper"]
        } else {
            throw WireError.unavailable
        }
        if let directory = ProcessInfo.processInfo.environment["CLASSIC_DROP_DATA_DIRECTORY"] {
            child.arguments = (child.arguments ?? []) + ["--data-directory", directory]
        }
        let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
        child.standardInput = stdin; child.standardOutput = stdout; child.standardError = stderr
        input = stdin.fileHandleForWriting
        stderr.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if !data.isEmpty { FileHandle.standardError.write(data) }
        }
        stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let self else { return }
            self.reader.async {
                do {
                    for line in try self.lines.append(data) {
                        let envelope = try Wire.decoder.decode(Envelope.self, from: line)
                        guard envelope.version == 1 else { throw WireError.incompatible }
                        DispatchQueue.main.async { self.onEvent?(envelope) }
                    }
                } catch {
                    DispatchQueue.main.async { self.onExit?(-2) }
                    // A mismatched stream never grants write authority. Keep the
                    // process alive until close/cancel has completed.
                }
            }
        }
        child.terminationHandler = { [weak self] child in
            stdout.fileHandleForReading.readabilityHandler = nil
            stderr.fileHandleForReading.readabilityHandler = nil
            self?.reader.async {
                DispatchQueue.main.async {
                    self?.input = nil; self?.process = nil
                    self?.onExit?(child.terminationStatus)
                }
            }
        }
        try child.run()
        process = child
    }

    func send(_ command: RequestDTO) throws {
        guard running, let input else { throw WireError.unavailable }
        var data = try Wire.encoder.encode(command)
        guard data.count <= Wire.maximumMessage else { throw WireError.oversized }
        data.append(10)
        writer.async { [weak self] in
            do { try input.write(contentsOf: data) }
            catch { DispatchQueue.main.async { self?.onExit?(-3) } }
        }
    }
}
