import Foundation

/// User overrides from Settings. Empty/nil means auto-detect.
public struct ToolOverrides: Codable, Equatable, Sendable {
    public var pythonPath: String?
    public var ffmpegPath: String?
    public var editorPath: String?

    public init(pythonPath: String? = nil, ffmpegPath: String? = nil, editorPath: String? = nil) {
        self.pythonPath = pythonPath
        self.ffmpegPath = ffmpegPath
        self.editorPath = editorPath
    }
}

/// Where the external pieces live. The editor root is the folder that *contains*
/// the `clipthat_editor` package, so `python3 -m clipthat_editor` works from it.
public struct ToolLocations: Equatable, Sendable {
    public var python: URL?
    public var ffmpeg: URL?
    public var ffprobe: URL?
    public var editorRoot: URL?

    public init(python: URL? = nil, ffmpeg: URL? = nil, ffprobe: URL? = nil, editorRoot: URL? = nil) {
        self.python = python
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.editorRoot = editorRoot
    }

    public var missing: [String] {
        var names: [String] = []
        if python == nil { names.append("python3") }
        if ffmpeg == nil { names.append("ffmpeg") }
        if ffprobe == nil { names.append("ffprobe") }
        if editorRoot == nil { names.append("clipthat_editor") }
        return names
    }

    public var isComplete: Bool { missing.isEmpty }
}

public struct ToolCheck: Identifiable, Equatable, Sendable {
    public var id: String { name }
    public var name: String
    public var ok: Bool
    public var detail: String
}

public enum Toolchain {
    /// GUI apps on macOS don't inherit the shell PATH, so Homebrew's folders are
    /// searched explicitly. /usr/bin comes last: its python3 is a stub that may ask
    /// to install the Command Line Tools.
    public static let searchDirectories = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]

    public static func locate(overrides: ToolOverrides = ToolOverrides(), bundledEditor: URL? = nil,
                              environment: [String: String] = ProcessInfo.processInfo.environment) -> ToolLocations {
        let python = findExecutable(["python3"], override: overrides.pythonPath,
                                    envKey: "CLIPTHAT_PYTHON", environment: environment)
        let ffmpeg = findExecutable(["ffmpeg"], override: overrides.ffmpegPath,
                                    envKey: "CLIPTHAT_FFMPEG", environment: environment)
        // Prefer the ffprobe next to the chosen ffmpeg so they come from the same build.
        var ffprobe: URL?
        if let ffmpeg {
            let sibling = ffmpeg.deletingLastPathComponent().appendingPathComponent("ffprobe")
            if isExecutable(sibling) { ffprobe = sibling }
        }
        if ffprobe == nil {
            ffprobe = findExecutable(["ffprobe"], override: nil, envKey: "CLIPTHAT_FFPROBE", environment: environment)
        }
        return ToolLocations(python: python, ffmpeg: ffmpeg, ffprobe: ffprobe,
                             editorRoot: locateEditor(override: overrides.editorPath, bundled: bundledEditor,
                                                      environment: environment))
    }

    public static func locateEditor(override: String?, bundled: URL?,
                                    environment: [String: String]) -> URL? {
        var candidates: [URL] = []
        if let override, !override.isEmpty { candidates.append(URL(fileURLWithPath: (override as NSString).expandingTildeInPath)) }
        if let env = environment["CLIPTHAT_EDITOR_DIR"], !env.isEmpty { candidates.append(URL(fileURLWithPath: env)) }
        if let bundled { candidates.append(bundled) }
        for candidate in candidates {
            if isEditorRoot(candidate) { return candidate }
            // Also accept a path pointing at the package folder itself.
            if candidate.lastPathComponent == "clipthat_editor",
               isEditorRoot(candidate.deletingLastPathComponent()) {
                return candidate.deletingLastPathComponent()
            }
        }
        return nil
    }

    public static func isEditorRoot(_ url: URL) -> Bool {
        let pkg = url.appendingPathComponent("clipthat_editor")
        let fm = FileManager.default
        return fm.fileExists(atPath: pkg.appendingPathComponent("__main__.py").path)
            && fm.fileExists(atPath: pkg.appendingPathComponent("engine.py").path)
    }

    static func findExecutable(_ names: [String], override: String?, envKey: String,
                               environment: [String: String]) -> URL? {
        if let override, !override.isEmpty {
            let url = URL(fileURLWithPath: (override as NSString).expandingTildeInPath)
            return isExecutable(url) ? url : nil
        }
        if let env = environment[envKey], !env.isEmpty {
            let url = URL(fileURLWithPath: env)
            if isExecutable(url) { return url }
        }
        let pathDirs = (environment["PATH"] ?? "").split(separator: ":").map(String.init)
        // Homebrew first, then the inherited PATH, then the system folders.
        let order: [String] = Array(searchDirectories.prefix(2)) + pathDirs + Array(searchDirectories.dropFirst(2))
        var seen = Set<String>()
        for dir in order where seen.insert(dir).inserted {
            for name in names {
                let url = URL(fileURLWithPath: dir).appendingPathComponent(name)
                if isExecutable(url) { return url }
            }
        }
        return nil
    }

    static func isExecutable(_ url: URL) -> Bool {
        var isDir: ObjCBool = false
        return FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir) && !isDir.boolValue
            && FileManager.default.isExecutableFile(atPath: url.path)
    }

    /// Environment for editor/ffmpeg child processes.
    public static func childEnvironment(for tools: ToolLocations,
                                        base: [String: String] = ProcessInfo.processInfo.environment) -> [String: String] {
        var env = base
        var dirs: [String] = []
        if let ffmpeg = tools.ffmpeg { dirs.append(ffmpeg.deletingLastPathComponent().path) }
        if let ffprobe = tools.ffprobe { dirs.append(ffprobe.deletingLastPathComponent().path) }
        dirs += searchDirectories
        dirs += (base["PATH"] ?? "").split(separator: ":").map(String.init)
        var seen = Set<String>()
        env["PATH"] = dirs.filter { seen.insert($0).inserted }.joined(separator: ":")
        if let root = tools.editorRoot { env["PYTHONPATH"] = root.path }
        // The bundled editor lives inside the signed app: never write __pycache__ there.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        return env
    }

    /// Health checks shown in Settings → Engine.
    public static func check(_ tools: ToolLocations) async -> [ToolCheck] {
        let env = childEnvironment(for: tools)
        var checks: [ToolCheck] = []

        if let python = tools.python {
            let r = try? await ProcessRunner.run(python, ["-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
                                                 environment: env)
            let version = r?.stdout.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            checks.append(ToolCheck(name: "Python", ok: r?.status == 0,
                                    detail: r?.status == 0 ? "\(version) · \(python.path)" : "Found \(python.path) but it didn't run"))
        } else {
            checks.append(ToolCheck(name: "Python", ok: false, detail: "Not found. Install with: brew install python"))
        }

        for (name, url) in [("FFmpeg", tools.ffmpeg), ("FFprobe", tools.ffprobe)] {
            if let url {
                let r = try? await ProcessRunner.run(url, ["-version"], environment: env)
                let first = r?.stdout.split(separator: "\n").first.map(String.init) ?? ""
                checks.append(ToolCheck(name: name, ok: r?.status == 0, detail: r?.status == 0 ? first : "Found \(url.path) but it didn't run"))
            } else {
                checks.append(ToolCheck(name: name, ok: false, detail: "Not found. Install with: brew install ffmpeg"))
            }
        }

        if let root = tools.editorRoot, let python = tools.python {
            let r = try? await ProcessRunner.run(python, ["-m", "clipthat_editor", "--help"],
                                                 currentDirectory: root, environment: env)
            checks.append(ToolCheck(name: "Editor", ok: r?.status == 0,
                                    detail: r?.status == 0 ? "clipthat_editor · \(root.path)"
                                        : "clipthat_editor failed to start: \(r?.stderr.suffix(300) ?? "")"))
        } else {
            checks.append(ToolCheck(name: "Editor", ok: false,
                                    detail: tools.editorRoot == nil ? "clipthat_editor not found" : "Needs Python"))
        }
        return checks
    }
}
