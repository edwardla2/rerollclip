import Foundation

// MARK: - Render options (values must match the editor contract, schema_version 1)

public enum RenderStyle: String, Codable, CaseIterable, Identifiable, Sendable {
    case clean
    case cinematic
    case highEnergy = "high_energy"

    public var id: String { rawValue }

    public var label: String {
        switch self {
        case .clean: return "Clean"
        case .cinematic: return "Cinematic"
        case .highEnergy: return "High energy"
        }
    }
}

public enum RenderLayout: String, Codable, CaseIterable, Identifiable, Sendable {
    case fitBlur = "fit_blur"
    case centerCrop = "center_crop"

    public var id: String { rawValue }

    public var label: String {
        switch self {
        case .fitBlur: return "Full frame + blur"
        case .centerCrop: return "Center crop"
        }
    }
}

// MARK: - Clips

/// Where a clip came from. Third-party recorder files are always "imports":
/// Clip That never claims to control another recorder.
public enum ClipOrigin: String, Codable, Sendable {
    case replay
    case folderImport = "folder_import"
    case fileImport = "file_import"
}

/// What fired a replay save.
public enum ClipTrigger: String, Codable, Sendable {
    case voice
    case hotkey
    case button
}

public struct Clip: Codable, Identifiable, Hashable, Sendable {
    public var id: String
    /// Path relative to the session folder, e.g. "clips/replay-20261024-181403-voice.mp4".
    /// Relative so the session folder can move and the manifest stays valid.
    public var relativePath: String
    public var origin: ClipOrigin
    public var trigger: ClipTrigger?
    /// For imports: the watched folder name or original location shown in the UI.
    public var importedFrom: String?
    public var originalFileName: String?
    public var capturedAt: Date
    /// Container duration as reported by ffprobe (same source the editor validates against).
    public var mediaDuration: Double
    public var selectionStart: Double
    public var selectionDuration: Double
    /// Seconds into the file where the trigger fired (replay clips only).
    public var triggerOffset: Double?
    public var hasAudio: Bool
    /// True when the file carries the raw microphone as an extra audio track.
    public var hasMicTrack: Bool

    public init(id: String = Clip.makeID(), relativePath: String, origin: ClipOrigin,
                trigger: ClipTrigger? = nil, importedFrom: String? = nil, originalFileName: String? = nil,
                capturedAt: Date, mediaDuration: Double, selectionStart: Double? = nil,
                selectionDuration: Double? = nil, triggerOffset: Double? = nil,
                hasAudio: Bool, hasMicTrack: Bool = false) {
        let selection = ClipSelection.defaultSelection(mediaDuration: mediaDuration)
        self.id = id
        self.relativePath = relativePath
        self.origin = origin
        self.trigger = trigger
        self.importedFrom = importedFrom
        self.originalFileName = originalFileName
        self.capturedAt = capturedAt
        self.mediaDuration = mediaDuration
        self.selectionStart = selectionStart ?? selection.start
        self.selectionDuration = selectionDuration ?? selection.duration
        self.triggerOffset = triggerOffset
        self.hasAudio = hasAudio
        self.hasMicTrack = hasMicTrack
    }

    public static func makeID() -> String {
        "clip-" + UUID().uuidString.prefix(8).lowercased()
    }

    /// Short provenance label for the UI, e.g. "Replay · Voice" or "Import · OBS".
    public var sourceLabel: String {
        switch origin {
        case .replay:
            switch trigger {
            case .voice: return "Replay · Voice"
            case .hotkey: return "Replay · Hotkey"
            case .button, .none: return "Replay"
            }
        case .folderImport:
            return "Import · " + (importedFrom ?? "Folder")
        case .fileImport:
            return "Import"
        }
    }

    public var displayName: String {
        originalFileName ?? (relativePath as NSString).lastPathComponent
    }
}

// MARK: - Sessions

public struct RenderSettings: Codable, Equatable, Hashable, Sendable {
    public var style: RenderStyle
    public var layout: RenderLayout
    public var width: Int
    public var height: Int
    public var fps: Int
    /// Relative to the session folder (music is copied in so the session is self-contained).
    public var musicRelativePath: String?
    public var musicVolume: Double

    public init(style: RenderStyle = .highEnergy, layout: RenderLayout = .fitBlur,
                width: Int = 1080, height: Int = 1920, fps: Int = 30,
                musicRelativePath: String? = nil, musicVolume: Double = 0.15) {
        self.style = style
        self.layout = layout
        self.width = width
        self.height = height
        self.fps = fps
        self.musicRelativePath = musicRelativePath
        self.musicVolume = musicVolume
    }
}

public struct RenderRecord: Codable, Identifiable, Hashable, Sendable {
    public var id: String
    public var relativePath: String
    public var createdAt: Date
    public var clipCount: Int
    public var style: RenderStyle
    public var layout: RenderLayout

    public init(id: String = "render-" + UUID().uuidString.prefix(8).lowercased(), relativePath: String,
                createdAt: Date, clipCount: Int, style: RenderStyle, layout: RenderLayout) {
        self.id = id
        self.relativePath = relativePath
        self.createdAt = createdAt
        self.clipCount = clipCount
        self.style = style
        self.layout = layout
    }
}

public struct Session: Codable, Identifiable, Hashable, Sendable {
    public var id: String
    public var title: String
    public var createdAt: Date
    /// Array order is montage order.
    public var clips: [Clip]
    public var settings: RenderSettings
    public var renders: [RenderRecord]
    /// Version of session.json (desktop-internal, not the editor manifest version).
    public var formatVersion: Int

    public init(id: String, title: String, createdAt: Date, clips: [Clip] = [],
                settings: RenderSettings = RenderSettings(), renders: [RenderRecord] = []) {
        self.id = id
        self.title = title
        self.createdAt = createdAt
        self.clips = clips
        self.settings = settings
        self.renders = renders
        self.formatVersion = 1
    }

    public var totalSelectedSeconds: Double {
        clips.reduce(0) { $0 + $1.selectionDuration }
    }
}

// MARK: - Formatting

public enum DurationFormat {
    /// 75.4 -> "1:15", 9.2 -> "0:09"
    public static func clock(_ seconds: Double) -> String {
        guard seconds.isFinite, seconds > 0 else { return "0:00" }
        let total = Int(seconds.rounded())
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    /// 9.25 -> "9.3s"
    public static func short(_ seconds: Double) -> String {
        String(format: "%.1fs", seconds)
    }
}
