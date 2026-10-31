import Foundation
import CryptoKit
import ImageIO

protocol ArtworkCaching: Actor {
    func read(namespace: String, id: String) async -> Data?
    func write(_ data: Data, namespace: String, id: String) async
}

/// Disposable Host thumbnails. Actor isolation keeps all filesystem work off the UI actor.
actor ArtworkDiskCache: ArtworkCaching {
    private let root: URL
    private let budget: Int
    private let manager = FileManager.default
    private var totalBytes: Int?
    private static let maximumPayload = 512 * 1024

    init(root: URL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("ClassicDrop/Artwork-v1", isDirectory: true),
        budget: Int = 512 * 1024 * 1024) {
        self.root = root
        self.budget = max(0, budget)
    }

    func read(namespace: String, id: String) -> Data? {
        let url = file(namespace: namespace, id: id)
        let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize
        guard let size,
              size > 0, size <= Self.maximumPayload,
              let data = try? Data(contentsOf: url), Self.valid(data) else {
            if (try? manager.removeItem(at: url)) != nil, let size, let totalBytes {
                self.totalBytes = max(0, totalBytes - size)
            }
            return nil
        }
        try? manager.setAttributes([.modificationDate: Date()], ofItemAtPath: url.path)
        return data
    }

    func write(_ data: Data, namespace: String, id: String) {
        guard !namespace.isEmpty, data.count <= budget, Self.valid(data) else { return }
        let url = file(namespace: namespace, id: id)
        do {
            if totalBytes == nil { prune() }
            let previousSize = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            try manager.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: url, options: .atomic)
            totalBytes = max(0, (totalBytes ?? 0) + data.count - previousSize)
            if (totalBytes ?? 0) > budget { prune() }
        } catch { /* A missing/unwritable cache never blocks device workflows. */ }
    }

    private func file(namespace: String, id: String) -> URL {
        func hash(_ text: String) -> String {
            SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
        }
        return root.appendingPathComponent(hash(namespace), isDirectory: true)
            .appendingPathComponent(hash(id) + ".png")
    }

    private static func valid(_ data: Data) -> Bool {
        guard !data.isEmpty, data.count <= maximumPayload,
              let source = CGImageSourceCreateWithData(data as CFData, nil),
              CGImageSourceGetCount(source) == 1,
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int,
              (1...320).contains(width), (1...320).contains(height) else { return false }
        return CGImageSourceCreateImageAtIndex(source, 0, nil) != nil
    }

    private func prune() {
        let keys: Set<URLResourceKey> = [.fileSizeKey, .contentModificationDateKey, .isRegularFileKey]
        guard let files = manager.enumerator(at: root, includingPropertiesForKeys: Array(keys)) else {
            totalBytes = 0; return
        }
        var entries: [(URL, Int, Date)] = []
        var total = 0
        for case let url as URL in files where url.pathExtension == "png" {
            guard let values = try? url.resourceValues(forKeys: keys), values.isRegularFile == true else { continue }
            let size = values.fileSize ?? 0
            entries.append((url, size, values.contentModificationDate ?? .distantPast))
            total += size
        }
        for (url, size, _) in entries.sorted(by: { $0.2 < $1.2 }) where total > budget {
            do { try manager.removeItem(at: url); total -= size } catch { continue }
        }
        totalBytes = total
    }
}
