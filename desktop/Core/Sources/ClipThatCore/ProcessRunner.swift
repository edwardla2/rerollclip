import Foundation

public struct ProcessOutput: Sendable {
    public var status: Int32
    public var stdout: String
    public var stderr: String
    public var wasCancelled: Bool
}

/// Thread-safe byte accumulator for pipe output.
private final class LockedBuffer: @unchecked Sendable {
    private var data = Data()
    private let lock = NSLock()
    func append(_ chunk: Data) {
        lock.lock(); data.append(chunk); lock.unlock()
    }
    func string() -> String {
        lock.lock(); defer { lock.unlock() }
        return String(decoding: data, as: UTF8.self)
    }
}

private final class CancelFlag: @unchecked Sendable {
    private var value = false
    private let lock = NSLock()
    func set() { lock.lock(); value = true; lock.unlock() }
    var isSet: Bool { lock.lock(); defer { lock.unlock() }; return value }
}

public enum ProcessRunner {
    /// Runs a child process to completion, collecting stdout/stderr.
    /// Swift task cancellation sends SIGINT first, so Python's `with TemporaryDirectory()`
    /// in the editor gets to clean up, then SIGTERM after a grace period.
    public static func run(_ executable: URL, _ arguments: [String], currentDirectory: URL? = nil,
                           environment: [String: String]? = nil) async throws -> ProcessOutput {
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        if let currentDirectory { process.currentDirectoryURL = currentDirectory }
        if let environment { process.environment = environment }

        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe
        process.standardInput = FileHandle.nullDevice

        let out = LockedBuffer()
        let err = LockedBuffer()
        let cancelled = CancelFlag()
        outPipe.fileHandleForReading.readabilityHandler = { handle in
            let chunk = handle.availableData
            if !chunk.isEmpty { out.append(chunk) }
        }
        errPipe.fileHandleForReading.readabilityHandler = { handle in
            let chunk = handle.availableData
            if !chunk.isEmpty { err.append(chunk) }
        }

        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<ProcessOutput, Error>) in
                process.terminationHandler = { finished in
                    outPipe.fileHandleForReading.readabilityHandler = nil
                    errPipe.fileHandleForReading.readabilityHandler = nil
                    out.append(outPipe.fileHandleForReading.readDataToEndOfFile())
                    err.append(errPipe.fileHandleForReading.readDataToEndOfFile())
                    continuation.resume(returning: ProcessOutput(status: finished.terminationStatus,
                                                                 stdout: out.string(), stderr: err.string(),
                                                                 wasCancelled: cancelled.isSet))
                }
                do {
                    try process.run()
                } catch {
                    process.terminationHandler = nil
                    outPipe.fileHandleForReading.readabilityHandler = nil
                    errPipe.fileHandleForReading.readabilityHandler = nil
                    continuation.resume(throwing: error)
                }
            }
        } onCancel: {
            cancelled.set()
            if process.isRunning {
                process.interrupt()
                DispatchQueue.global().asyncAfter(deadline: .now() + 3) {
                    if process.isRunning { process.terminate() }
                }
            }
        }
    }
}
