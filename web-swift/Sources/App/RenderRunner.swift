import Foundation
import Vapor

/// Runs the renderer CLI exactly as the Mac app does:
///   python3 -m clipthat_editor render <manifest> --output <mp4>
/// Arguments go straight to the process (no shell), so paths can't inject commands.
struct RenderRunner {
    let config: ClipThatConfig

    func render(manifestPath: String, outputPath: String) async throws {
        guard let executable = config.pythonCommand.first else {
            throw Abort(.internalServerError, reason: "Renderer is not configured")
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = Array(config.pythonCommand.dropFirst())
            + ["-m", "clipthat_editor", "render", manifestPath, "--output", outputPath]
        process.currentDirectoryURL = URL(fileURLWithPath: config.editorRoot)
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = config.editorRoot
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = env
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = FileHandle.nullDevice
        let stderr = Pipe()
        process.standardError = stderr

        // Set before run() so the exit can't be missed.
        let exits = AsyncStream<Int32> { continuation in
            process.terminationHandler = { finished in
                continuation.yield(finished.terminationStatus)
                continuation.finish()
            }
        }
        do {
            try process.run()
        } catch {
            throw Abort(.internalServerError, reason: "Couldn't start the renderer")
        }
        // Drain stderr concurrently so a chatty child can't block on a full pipe.
        let stderrText = Task.detached { () -> String in
            String(decoding: stderr.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        }
        let timedOut = Flag()
        let timeoutSeconds = config.renderTimeoutSeconds
        let watchdog = Task.detached {
            try? await Task.sleep(nanoseconds: UInt64(timeoutSeconds * 1_000_000_000))
            guard !Task.isCancelled, process.isRunning else { return }
            timedOut.set()
            process.terminate()
        }

        var status: Int32 = -1
        for await code in exits { status = code }
        watchdog.cancel()
        let log = await stderrText.value

        if timedOut.isSet {
            throw Abort(.gatewayTimeout, reason: "Render timed out")
        }
        guard status == 0 else {
            throw Abort(.unprocessableEntity, reason: "Render failed: \(Self.errorMessage(from: log, status: status))")
        }
    }

    /// The renderer prints `{"ok": false, "error": "..."}` as its last stderr line.
    static func errorMessage(from stderr: String, status: Int32) -> String {
        for line in stderr.split(separator: "\n").reversed() {
            if let data = line.data(using: .utf8),
               let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let message = object["error"] as? String {
                return message
            }
        }
        let tail = stderr.trimmingCharacters(in: .whitespacesAndNewlines)
        return tail.isEmpty ? "renderer exited with code \(status)" : String(tail.suffix(600))
    }
}

/// Thread-safe boolean for the render watchdog.
private final class Flag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false

    func set() {
        lock.lock()
        value = true
        lock.unlock()
    }

    var isSet: Bool {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}
