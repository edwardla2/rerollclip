import Foundation

/// Limits enforced by the renderer (clipthat_editor/engine.py `parse_manifest`, schema v1).
/// Every client validates against these so problems surface before a render starts.
public enum RendererLimits {
    public static let schemaVersion = 1
    public static let styles: Set<String> = ["clean", "cinematic", "high_energy"]
    public static let layouts: Set<String> = ["fit_blur", "center_crop"]
    public static let maxClips = 100
    public static let maxClipSeconds = 120.0
    /// The renderer accepts start + duration <= media duration + 0.25 s.
    public static let durationTolerance = 0.25
    public static let minDimension = 240
    public static let maxDimension = 3840
    public static let fpsRange = 1...120
}

/// Schema v1 manifest, shared by the macOS app and the Vapor website.
/// JSON field names match the Python/FFmpeg renderer and examples/manifest.example.json.
public struct ClipThatManifest: Codable, Sendable, Equatable {
    public struct Output: Codable, Sendable, Equatable {
        public var width: Int
        public var height: Int
        public var fps: Int
        public init(width: Int = 1080, height: Int = 1920, fps: Int = 30) {
            self.width = width
            self.height = height
            self.fps = fps
        }
    }

    public struct Clip: Codable, Sendable, Equatable {
        public var id: String
        public var file: String
        public var startSeconds: Double
        public var durationSeconds: Double
        public init(id: String, file: String, startSeconds: Double, durationSeconds: Double) {
            self.id = id
            self.file = file
            self.startSeconds = startSeconds
            self.durationSeconds = durationSeconds
        }
        enum CodingKeys: String, CodingKey {
            case id, file
            case startSeconds = "start_seconds"
            case durationSeconds = "duration_seconds"
        }
    }

    public struct Music: Codable, Sendable, Equatable {
        public var file: String
        public var volume: Double
        public init(file: String, volume: Double = 0.15) {
            self.file = file
            self.volume = volume
        }
    }

    public var schemaVersion: Int
    public var sessionID: String
    public var style: String
    public var layout: String
    public var output: Output
    public var clips: [Clip]
    public var music: Music?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sessionID = "session_id"
        case style, layout, output, clips, music
    }

    public init(sessionID: String, style: String = "clean", layout: String = "fit_blur", output: Output = .init(),
                clips: [Clip], music: Music? = nil) {
        self.schemaVersion = RendererLimits.schemaVersion
        self.sessionID = sessionID
        self.style = style
        self.layout = layout
        self.output = output
        self.clips = clips
        self.music = music
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try c.decode(Int.self, forKey: .schemaVersion)
        sessionID = try c.decodeIfPresent(String.self, forKey: .sessionID) ?? ""
        style = try c.decodeIfPresent(String.self, forKey: .style) ?? "clean"
        layout = try c.decodeIfPresent(String.self, forKey: .layout) ?? "fit_blur"
        output = try c.decodeIfPresent(Output.self, forKey: .output) ?? Output()
        clips = try c.decode([Clip].self, forKey: .clips)
        music = try c.decodeIfPresent(Music.self, forKey: .music)
    }

    /// Writes an explicit `"music": null`, as the reference example does.
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(schemaVersion, forKey: .schemaVersion)
        try c.encode(sessionID, forKey: .sessionID)
        try c.encode(style, forKey: .style)
        try c.encode(layout, forKey: .layout)
        try c.encode(output, forKey: .output)
        try c.encode(clips, forKey: .clips)
        if let music { try c.encode(music, forKey: .music) } else { try c.encodeNil(forKey: .music) }
    }

    public enum ValidationError: Error, Equatable, CustomStringConvertible {
        case invalid(String)
        public var description: String {
            switch self { case .invalid(let message): return message }
        }
    }

    /// Checks everything the renderer checks except file existence and media durations.
    /// Servers must still confine `file` paths to the project folder themselves.
    public func validate() throws {
        func require(_ condition: Bool, _ message: String) throws {
            if !condition { throw ValidationError.invalid(message) }
        }
        try require(schemaVersion == RendererLimits.schemaVersion, "Only manifest schema v1 is supported")
        try require(!sessionID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, "Session ID must not be empty")
        try require(RendererLimits.styles.contains(style), "Unsupported style")
        try require(RendererLimits.layouts.contains(layout), "Unsupported layout")
        let dims = [output.width, output.height]
        try require(dims.allSatisfy { $0 >= RendererLimits.minDimension && $0 <= RendererLimits.maxDimension && $0 % 2 == 0 }
                    && RendererLimits.fpsRange.contains(output.fps),
                    "Output dimensions must be even integers between 240 and 3840; fps 1-120")
        try require(!clips.isEmpty, "At least one clip is required")
        try require(clips.count <= RendererLimits.maxClips, "Limit of \(RendererLimits.maxClips) clips per render")
        for clip in clips {
            try require(!clip.id.isEmpty && !clip.file.isEmpty, "Clip ID and file are required")
            try require(clip.startSeconds.isFinite && clip.startSeconds >= 0, "Invalid clip start")
            try require(clip.durationSeconds.isFinite && clip.durationSeconds > 0
                        && clip.durationSeconds <= RendererLimits.maxClipSeconds,
                        "Clip duration must be between 0 and \(Int(RendererLimits.maxClipSeconds)) seconds")
        }
        if let music {
            try require(!music.file.isEmpty && music.volume.isFinite && (0...1).contains(music.volume),
                        "Invalid soundtrack configuration")
        }
    }

    public func jsonData(pretty: Bool = false) throws -> Data {
        try validate()
        let encoder = JSONEncoder()
        encoder.outputFormatting = pretty ? [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes] : [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(self)
    }
}
