import Foundation
import Vapor

/// Runs the editor CLI the same way the Mac app does:
///   python3 -m clipthat_editor <command> ...
/// Arguments go straight to the process (no shell), so paths can't inject commands.
struct EditorCLI {
    let config: ClipThatConfig

    struct Output {
        var status: Int32
        var stdout: String
        var stderr: String
        var timedOut: Bool
    }

    func run(_ arguments: [String], timeoutSeconds: Double) async throws -> Output {
        guard let executable = config.pythonCommand.first else {
            throw Abort(.internalServerError, reason: "Renderer is not configured")
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = Array(config.pythonCommand.dropFirst()) + ["-m", "clipthat_editor"] + arguments
        process.currentDirectoryURL = URL(fileURLWithPath: config.editorRoot)
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = config.editorRoot
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = env
        process.standardInput = FileHandle.nullDevice
        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe

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
        // Drain both pipes concurrently so a chatty child can't block on a full pipe.
        let stdoutText = Task.detached { String(decoding: outPipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self) }
        let stderrText = Task.detached { String(decoding: errPipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self) }
        let timedOut = Flag()
        let watchdog = Task.detached {
            try? await Task.sleep(nanoseconds: UInt64(timeoutSeconds * 1_000_000_000))
            guard !Task.isCancelled, process.isRunning else { return }
            timedOut.set()
            process.terminate()
        }

        var status: Int32 = -1
        for await code in exits { status = code }
        watchdog.cancel()
        return Output(status: status, stdout: await stdoutText.value, stderr: await stderrText.value,
                      timedOut: timedOut.isSet)
    }

    /// The editor prints `{"ok": false, "error": "..."}` as its last stderr line.
    static func errorMessage(from stderr: String, status: Int32) -> String {
        for line in stderr.split(separator: "\n").reversed() {
            if let data = line.data(using: .utf8),
               let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let message = object["error"] as? String {
                return message
            }
        }
        let tail = stderr.trimmingCharacters(in: .whitespacesAndNewlines)
        return tail.isEmpty ? "editor exited with code \(status)" : String(tail.suffix(600))
    }
}

struct RenderRunner {
    let config: ClipThatConfig

    func render(manifestPath: String, outputPath: String) async throws {
        let result = try await EditorCLI(config: config).run(["render", manifestPath, "--output", outputPath],
                                                             timeoutSeconds: config.renderTimeoutSeconds)
        if result.timedOut { throw Abort(.gatewayTimeout, reason: "Render timed out") }
        guard result.status == 0 else {
            throw Abort(.unprocessableEntity,
                        reason: "Render failed: \(EditorCLI.errorMessage(from: result.stderr, status: result.status))")
        }
    }
}

/// Thread-safe boolean for the watchdog.
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
