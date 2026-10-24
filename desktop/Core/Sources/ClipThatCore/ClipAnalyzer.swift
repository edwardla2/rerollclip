import Foundation

/// A suggested in/out window from `clipthat_editor analyze` (see clipthat_editor/analysis.py).
public struct TrimSuggestion: Decodable, Equatable, Sendable {
    public var duration: Double
    public var signals: [String]
    public var suggestedStart: Double
    public var suggestedDuration: Double
    public var peakTime: Double
    public var strength: Double

    enum CodingKeys: String, CodingKey {
        case duration, signals, strength
        case suggestedStart = "suggested_start"
        case suggestedDuration = "suggested_duration"
        case peakTime = "peak_time"
    }
}

/// Finds the moment worth keeping in a clip. For replay clips, pass the trigger offset:
/// the analyzer then only looks at the seconds before "Clip that" was said.
public enum ClipAnalyzer {
    public static func suggest(for file: URL, length: Double = 8, triggerOffset: Double? = nil,
                               tools: ToolLocations) async throws -> TrimSuggestion {
        guard let python = tools.python, let editorRoot = tools.editorRoot, tools.ffmpeg != nil else {
            throw RenderFailure.missingTools(tools.missing)
        }
        var args = ["-m", "clipthat_editor", "analyze", file.path, "--length", String(length)]
        if let triggerOffset { args += ["--trigger-offset", String(triggerOffset)] }
        let result = try await ProcessRunner.run(python, args, currentDirectory: editorRoot,
                                                 environment: Toolchain.childEnvironment(for: tools))
        guard result.status == 0 else {
            throw RenderFailure.engine(message: RendererOutput.errorMessage(stderr: result.stderr, status: result.status),
                                       log: result.stderr)
        }
        guard let line = result.stdout.split(separator: "\n").last, let data = line.data(using: .utf8),
              let suggestion = try? JSONDecoder().decode(TrimSuggestion.self, from: data) else {
            throw RenderFailure.engine(message: "The analyzer returned an unexpected result.", log: result.stdout)
        }
        return suggestion
    }
}
