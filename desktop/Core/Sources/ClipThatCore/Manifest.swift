import Foundation
@_exported import ClipThatContracts

public enum ClipSelection {
    /// Default in/out for a newly added clip. Whole clip when the editor can take it;
    /// for long recordings (over the 120 s per-clip limit) the last 30 s, since a
    /// saved moment usually ends at the point the recorder saved it.
    public static func defaultSelection(mediaDuration: Double) -> (start: Double, duration: Double) {
        guard mediaDuration > 0 else { return (0, 0) }
        if mediaDuration <= RendererLimits.maxClipSeconds {
            return (0, floorMillis(mediaDuration))
        }
        let length = 30.0
        return (floorMillis(mediaDuration - length), length)
    }

    /// Clamp a user selection to what both the media and the editor allow.
    public static func normalized(start: Double, duration: Double,
                                  mediaDuration: Double) -> (start: Double, duration: Double) {
        let media = max(0, mediaDuration)
        var s = start.isFinite ? max(0, start) : 0
        if media > 0 { s = min(s, max(0, media - 0.1)) }
        var d = duration.isFinite && duration > 0 ? duration : media
        d = min(d, RendererLimits.maxClipSeconds)
        if media > 0 { d = min(d, media - s) }
        d = max(d, 0.1)
        return (roundMillis(s), floorMillis(d))
    }

    static func roundMillis(_ x: Double) -> Double { (x * 1000).rounded() / 1000 }
    static func floorMillis(_ x: Double) -> Double { (x * 1000).rounded(.down) / 1000 }
}

public struct ManifestIssue: Error, Equatable, CustomStringConvertible, Sendable {
    public var clipID: String?
    public var message: String
    public var description: String { message }

    public init(clipID: String? = nil, _ message: String) {
        self.clipID = clipID
        self.message = message
    }
}

/// Builds the editor's manifest.json (contract v0.1, schema_version 1) from a session.
/// Writes exactly the keys in examples/manifest.example.json. Any new key goes
/// through the contract-change process in INTERFACE_NOTES.md first.
public enum ManifestBuilder {

    public static func issues(for session: Session,
                              fileExists: (String) -> Bool) -> [ManifestIssue] {
        var problems: [ManifestIssue] = []
        if session.clips.isEmpty {
            problems.append(ManifestIssue("Add at least one clip to render."))
        }
        if session.clips.count > RendererLimits.maxClips {
            problems.append(ManifestIssue("The editor accepts up to \(RendererLimits.maxClips) clips per render."))
        }
        let s = session.settings
        let dims = [s.width, s.height]
        if dims.contains(where: { $0 < RendererLimits.minDimension || $0 > RendererLimits.maxDimension || $0 % 2 != 0 })
            || !RendererLimits.fpsRange.contains(s.fps) {
            problems.append(ManifestIssue("Output size must be even, 240–3840 px, at 1–120 fps."))
        }
        if !(0...1).contains(s.musicVolume) {
            problems.append(ManifestIssue("Music volume must be between 0 and 1."))
        }
        if let music = s.musicRelativePath, !fileExists(music) {
            problems.append(ManifestIssue("The music file is missing. Choose it again or remove it."))
        }
        for clip in session.clips {
            if !fileExists(clip.relativePath) {
                problems.append(ManifestIssue(clipID: clip.id, "“\(clip.displayName)” is missing from the session folder."))
                continue
            }
            if clip.selectionStart < 0 || clip.selectionDuration <= 0
                || clip.selectionDuration > RendererLimits.maxClipSeconds {
                problems.append(ManifestIssue(clipID: clip.id,
                    "“\(clip.displayName)” needs a selection between 0.1 and \(Int(RendererLimits.maxClipSeconds)) seconds."))
            } else if clip.mediaDuration > 0,
                      clip.selectionStart + clip.selectionDuration > clip.mediaDuration + RendererLimits.durationTolerance {
                problems.append(ManifestIssue(clipID: clip.id, "“\(clip.displayName)” selection runs past the end of the clip."))
            }
        }
        return problems
    }

    public static func manifest(for session: Session) -> ClipThatManifest {
        ClipThatManifest(
            sessionID: session.id,
            style: session.settings.style.rawValue,
            layout: session.settings.layout.rawValue,
            output: .init(width: session.settings.width, height: session.settings.height, fps: session.settings.fps),
            clips: session.clips.map { clip in
                let sel = ClipSelection.normalized(start: clip.selectionStart, duration: clip.selectionDuration,
                                                   mediaDuration: clip.mediaDuration)
                return .init(id: clip.id, file: clip.relativePath, startSeconds: sel.start, durationSeconds: sel.duration)
            },
            music: session.settings.musicRelativePath.map { .init(file: $0, volume: session.settings.musicVolume) }
        )
    }

    public static func manifestData(for session: Session) throws -> Data {
        try manifest(for: session).jsonData(pretty: true)
    }
}
