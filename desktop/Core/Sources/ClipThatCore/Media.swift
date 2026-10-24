import Foundation

public struct MediaInfo: Equatable, Sendable {
    public var duration: Double
    public var hasVideo: Bool
    public var audioStreamCount: Int
    public var width: Int?
    public var height: Int?

    public var hasAudio: Bool { audioStreamCount > 0 }
}

public enum MediaError: Error, LocalizedError {
    case toolMissing(String)
    case unreadable(String)
    case noVideo(String)
    case conversionFailed(String)

    public var errorDescription: String? {
        switch self {
        case .toolMissing(let name): return "\(name) isn't installed. Open Settings → Engine."
        case .unreadable(let file): return "Couldn't read “\(file)” as a video."
        case .noVideo(let file): return "“\(file)” has no video track."
        case .conversionFailed(let detail): return "Couldn't convert the file: \(detail)"
        }
    }
}

/// Uses ffprobe, the same tool the editor validates with, so durations agree.
public enum MediaProbe {
    public static func probe(_ url: URL, tools: ToolLocations) async throws -> MediaInfo {
        guard let ffprobe = tools.ffprobe else { throw MediaError.toolMissing("ffprobe") }
        let r = try await ProcessRunner.run(ffprobe, ["-v", "error", "-show_format", "-show_streams", "-of", "json", url.path],
                                            environment: Toolchain.childEnvironment(for: tools))
        guard r.status == 0, let data = r.stdout.data(using: .utf8) else {
            throw MediaError.unreadable(url.lastPathComponent)
        }
        return try parse(data, name: url.lastPathComponent)
    }

    public static func parse(_ data: Data, name: String) throws -> MediaInfo {
        struct Probe: Decodable {
            struct Stream: Decodable {
                var codec_type: String?
                var width: Int?
                var height: Int?
            }
            struct Format: Decodable { var duration: String? }
            var streams: [Stream]?
            var format: Format?
        }
        guard let probe = try? JSONDecoder().decode(Probe.self, from: data) else {
            throw MediaError.unreadable(name)
        }
        let streams = probe.streams ?? []
        let video = streams.first { $0.codec_type == "video" }
        return MediaInfo(duration: Double(probe.format?.duration ?? "") ?? 0,
                         hasVideo: video != nil,
                         audioStreamCount: streams.filter { $0.codec_type == "audio" }.count,
                         width: video?.width, height: video?.height)
    }
}

/// Brings outside video files into a session folder.
public enum ClipImporter {
    /// Formats the editor and the in-app preview both handle directly.
    public static let directExtensions: Set<String> = ["mp4", "mov", "m4v"]
    /// Recorder formats (OBS defaults to MKV) that get remuxed to MP4 on import.
    public static let remuxExtensions: Set<String> = ["mkv", "flv", "webm", "ts", "avi"]
    public static var supportedExtensions: Set<String> { directExtensions.union(remuxExtensions) }

    public static func isSupported(_ url: URL) -> Bool {
        supportedExtensions.contains(url.pathExtension.lowercased())
    }

    /// Copies (APFS clone, so no extra disk) or remuxes `source` into the session's clips
    /// folder and returns a Clip. The caller appends it to the session and saves.
    public static func importFile(_ source: URL, into session: Session, store: SessionStore,
                                  tools: ToolLocations, origin: ClipOrigin, importedFrom: String?,
                                  now: Date = Date()) async throws -> Clip {
        let ext = source.pathExtension.lowercased()
        guard supportedExtensions.contains(ext) else { throw MediaError.unreadable(source.lastPathComponent) }
        let stem = source.deletingPathExtension().lastPathComponent
        let base = "import-" + SessionStore.stamp(now) + "-" + SessionStore.sanitize(stem)
        let needsRemux = !directExtensions.contains(ext)
        let dest = try store.uniqueDestination(in: session, folder: "clips", baseName: base,
                                               ext: needsRemux ? "mp4" : ext)
        if needsRemux {
            try await remux(source, to: dest.url, tools: tools)
        } else {
            try FileManager.default.copyItem(at: source, to: dest.url)
        }

        let info: MediaInfo
        do {
            info = try await MediaProbe.probe(dest.url, tools: tools)
            guard info.hasVideo else { throw MediaError.noVideo(source.lastPathComponent) }
        } catch {
            try? FileManager.default.removeItem(at: dest.url)
            throw error
        }

        let attrs = try? FileManager.default.attributesOfItem(atPath: source.path)
        let captured = (attrs?[.creationDate] as? Date) ?? (attrs?[.modificationDate] as? Date) ?? now
        return Clip(relativePath: dest.relativePath, origin: origin, importedFrom: importedFrom,
                    originalFileName: source.lastPathComponent, capturedAt: captured,
                    mediaDuration: info.duration, hasAudio: info.hasAudio,
                    hasMicTrack: false)
    }

    /// Stream copy first (fast, lossless); re-encode if the codecs don't fit in MP4.
    static func remux(_ source: URL, to dest: URL, tools: ToolLocations) async throws {
        guard let ffmpeg = tools.ffmpeg else { throw MediaError.toolMissing("ffmpeg") }
        let env = Toolchain.childEnvironment(for: tools)
        let copy = try await ProcessRunner.run(ffmpeg, remuxArguments(source: source, dest: dest, reencode: false),
                                               environment: env)
        if copy.status == 0 { return }
        try? FileManager.default.removeItem(at: dest)
        let encode = try await ProcessRunner.run(ffmpeg, remuxArguments(source: source, dest: dest, reencode: true),
                                                 environment: env)
        if encode.status != 0 {
            try? FileManager.default.removeItem(at: dest)
            throw MediaError.conversionFailed(String(encode.stderr.suffix(300)))
        }
    }

    public static func remuxArguments(source: URL, dest: URL, reencode: Bool) -> [String] {
        var args = ["-hide_banner", "-loglevel", "error", "-y", "-i", source.path,
                    "-map", "0:v:0", "-map", "0:a?"]
        if reencode {
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "160k"]
        } else {
            args += ["-c", "copy"]
        }
        args += ["-movflags", "+faststart", dest.path]
        return args
    }
}
