import Foundation

/// Watches recorder export folders by polling. Polling a handful of folders every
/// couple of seconds is cheap, behaves the same on every OS, and copes with recorders
/// that write a file over several seconds: a file is reported only once its size has
/// stopped changing for `requiredStablePolls` consecutive polls.
///
/// Files already present when a folder is first seen are ignored; only new exports import.
public final class FolderScanner {
    public var requiredStablePolls: Int
    private var known: [String: Set<String>] = [:]          // folder path -> file names handled
    private var pending: [String: (size: UInt64, stable: Int)] = [:]  // file path -> observation

    public init(requiredStablePolls: Int = 2) {
        self.requiredStablePolls = requiredStablePolls
    }

    /// Returns newly finished files across `folders`, oldest observation first.
    public func poll(_ folders: [URL]) -> [URL] {
        var ready: [URL] = []
        let active = Set(folders.map(\.standardizedFileURL.path))
        known = known.filter { active.contains($0.key) }

        for folder in folders {
            let key = folder.standardizedFileURL.path
            let names = Self.candidateNames(in: folder)
            guard var seen = known[key] else {
                known[key] = Set(names)   // first sight: existing files are history
                continue
            }
            for name in names where !seen.contains(name) {
                let url = folder.appendingPathComponent(name)
                let size = Self.size(of: url)
                if let prior = pending[url.path], prior.size == size, size > 0 {
                    let stable = prior.stable + 1
                    if stable >= requiredStablePolls {
                        pending[url.path] = nil
                        seen.insert(name)
                        ready.append(url)
                    } else {
                        pending[url.path] = (size, stable)
                    }
                } else {
                    pending[url.path] = (size, 0)
                }
            }
            // Forget names that disappeared so a re-export with the same name imports again.
            seen = seen.intersection(names)
            known[key] = seen
        }
        return ready
    }

    public static func isCandidate(_ name: String) -> Bool {
        if name.hasPrefix(".") || name.contains("~") { return false }
        let lower = name.lowercased()
        for partial in [".part", ".tmp", ".crdownload", ".download", ".partial"] where lower.hasSuffix(partial) {
            return false
        }
        return ClipImporter.supportedExtensions.contains((lower as NSString).pathExtension)
    }

    static func candidateNames(in folder: URL) -> Set<String> {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: folder.path) else { return [] }
        return Set(names.filter(isCandidate))
    }

    static func size(of url: URL) -> UInt64 {
        let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
        return (attrs?[.size] as? NSNumber)?.uint64Value ?? 0
    }
}
