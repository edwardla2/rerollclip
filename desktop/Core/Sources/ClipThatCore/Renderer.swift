import Foundation

public struct RenderSuccess: Equatable, Sendable {
    public var output: URL
    public var clipCount: Int
    public var width: Int
    public var height: Int
    public var fps: Int
}

public enum RenderFailure: Error, LocalizedError, Equatable {
    case missingTools([String])
    case invalidSession([ManifestIssue])
    case engine(message: String, log: String)
    case cancelled

    public var errorDescription: String? {
        switch self {
        case .missingTools(let names):
            return "Can't render yet: missing \(names.joined(separator: ", ")). Open Settings → Engine."
        case .invalidSession(let issues):
            return issues.map(\.message).joined(separator: "\n")
        case .engine(let message, _):
            return message
        case .cancelled:
            return "Render cancelled."
        }
    }

    public var log: String {
        if case .engine(_, let log) = self { return log }
        return ""
    }
}

/// Invokes ChatGPT's editor exactly per the v0.1 contract:
///   python -m clipthat_editor render /ABS/manifest.json --output /ABS/render.mp4
public enum Renderer {

    public static func render(session: Session, store: SessionStore, tools: ToolLocations,
                              now: Date = Date()) async throws -> (RenderSuccess, RenderRecord) {
        guard let python = tools.python, let editorRoot = tools.editorRoot, tools.ffmpeg != nil else {
            throw RenderFailure.missingTools(tools.missing)
        }
        let issues = ManifestBuilder.issues(for: session) { store.fileExists($0, in: session) }
        guard issues.isEmpty else { throw RenderFailure.invalidSession(issues) }

        let manifestURL = store.manifestURL(for: session)
        try ManifestBuilder.manifestData(for: session).write(to: manifestURL, options: .atomic)

        let destination = try store.uniqueDestination(in: session, folder: "renders",
                                                      baseName: "montage-" + SessionStore.stamp(now), ext: "mp4")
        let args = ["-m", "clipthat_editor", "render", manifestURL.path, "--output", destination.url.path]

        let result: ProcessOutput
        do {
            result = try await ProcessRunner.run(python, args, currentDirectory: editorRoot,
                                                 environment: Toolchain.childEnvironment(for: tools))
        } catch {
            throw RenderFailure.engine(message: "Couldn't start the editor: \(error.localizedDescription)", log: "")
        }

        if result.wasCancelled || Task.isCancelled {
            try? FileManager.default.removeItem(at: destination.url)
            throw RenderFailure.cancelled
        }
        guard result.status == 0 else {
            try? FileManager.default.removeItem(at: destination.url)
            throw RenderFailure.engine(message: RendererOutput.errorMessage(stderr: result.stderr, status: result.status),
                                       log: RendererOutput.log(command: [python.path] + args, result: result))
        }
        guard FileManager.default.fileExists(atPath: destination.url.path) else {
            throw RenderFailure.engine(message: "The editor reported success but no video was written.",
                                       log: RendererOutput.log(command: [python.path] + args, result: result))
        }
        let parsed = RendererOutput.success(stdout: result.stdout)
        let success = RenderSuccess(output: destination.url,
                                    clipCount: parsed?.clips ?? session.clips.count,
                                    width: parsed?.width ?? session.settings.width,
                                    height: parsed?.height ?? session.settings.height,
                                    fps: parsed?.fps ?? session.settings.fps)
        let record = RenderRecord(relativePath: destination.relativePath, createdAt: now,
                                  clipCount: success.clipCount, style: session.settings.style,
                                  layout: session.settings.layout)
        return (success, record)
    }
}

/// Parses the editor's JSON lines: success on stdout, `{"ok": false, "error": ...}` on stderr.
public enum RendererOutput {
    public struct Success: Decodable, Equatable {
        public var ok: Bool
        public var output: String?
        public var clips: Int?
        public var width: Int?
        public var height: Int?
        public var fps: Int?
    }

    struct Failure: Decodable {
        var ok: Bool
        var error: String
    }

    public static func success(stdout: String) -> Success? {
        for line in stdout.split(separator: "\n").reversed() {
            if let data = line.data(using: .utf8),
               let value = try? JSONDecoder().decode(Success.self, from: data), value.ok {
                return value
            }
        }
        return nil
    }

    public static func errorMessage(stderr: String, status: Int32) -> String {
        for line in stderr.split(separator: "\n").reversed() {
            if let data = line.data(using: .utf8),
               let value = try? JSONDecoder().decode(Failure.self, from: data), !value.ok {
                return value.error
            }
        }
        let tail = stderr.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: "\n").suffix(3).joined(separator: "\n")
        return tail.isEmpty ? "The editor exited with code \(status)." : tail
    }

    public static func log(command: [String], result: ProcessOutput) -> String {
        """
        $ \(command.map { $0.contains(" ") ? "'\($0)'" : $0 }.joined(separator: " "))
        exit status: \(result.status)

        --- stdout ---
        \(result.stdout)
        --- stderr ---
        \(result.stderr)
        """
    }
}
