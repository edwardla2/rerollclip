import Foundation

/// One short encoded file in the rolling replay buffer. Times are host-clock seconds
/// (the clock ScreenCaptureKit stamps samples with).
public struct ReplaySegment: Equatable, Sendable {
    public var url: URL
    public var start: Double
    public var end: Double
    /// Segments can only be joined when their track layout matches.
    public var signature: String

    public init(url: URL, start: Double, end: Double, signature: String) {
        self.url = url
        self.start = start
        self.end = end
        self.signature = signature
    }

    public var duration: Double { end - start }
}

/// Bookkeeping for the rolling buffer: which segments exist, which to delete, and which
/// to stitch for a "clip that". Pure logic, no I/O, so it's unit-tested on any OS.
public struct SegmentRing: Sendable {
    public private(set) var segments: [ReplaySegment] = []
    /// Keep segments whose end is within this many seconds of the newest segment.
    public var retention: Double
    private var pinned: [URL: Int] = [:]
    private var evictedWhilePinned: Set<URL> = []

    public init(retention: Double) {
        self.retention = retention
    }

    /// Seconds of footage currently held, newest end back to oldest start.
    public var bufferedSeconds: Double {
        guard let first = segments.first, let last = segments.last else { return 0 }
        return last.end - first.start
    }

    /// Adds a finished segment. Returns files that are now safe to delete.
    public mutating func append(_ segment: ReplaySegment) -> [URL] {
        segments.append(segment)
        segments.sort { $0.start < $1.start }
        let cutoff = (segments.last?.end ?? segment.end) - retention
        var kept: [ReplaySegment] = []
        var deletable: [URL] = []
        for old in segments {
            if old.end >= cutoff {
                kept.append(old)
            } else if pinned[old.url, default: 0] > 0 {
                evictedWhilePinned.insert(old.url)
            } else {
                deletable.append(old.url)
            }
        }
        segments = kept
        return deletable
    }

    /// Segments covering roughly [end - duration, end]: the newest contiguous run with one
    /// track signature. Starts at a segment boundary, so the clip can be up to one segment
    /// longer than `duration`.
    public func selection(endingAt end: Double, duration: Double) -> [ReplaySegment] {
        let candidates = segments.filter { $0.start < end && $0.end > end - duration }
        guard let newest = candidates.last else { return [] }
        var run: [ReplaySegment] = []
        for segment in candidates.reversed() {
            guard segment.signature == newest.signature else { break }
            run.append(segment)
        }
        return run.reversed()
    }

    public mutating func pin(_ urls: [URL]) {
        for url in urls { pinned[url, default: 0] += 1 }
    }

    /// Releases a pin. Returns files that were evicted while pinned and can now be deleted.
    public mutating func unpin(_ urls: [URL]) -> [URL] {
        var deletable: [URL] = []
        for url in urls {
            let n = pinned[url, default: 0] - 1
            if n <= 0 {
                pinned[url] = nil
                if evictedWhilePinned.remove(url) != nil { deletable.append(url) }
            } else {
                pinned[url] = n
            }
        }
        return deletable
    }

    /// Everything on disk (for wiping the buffer when capture stops).
    public var allFiles: [URL] {
        segments.map(\.url) + Array(evictedWhilePinned)
    }

    public mutating func removeAll() {
        segments.removeAll()
        pinned.removeAll()
        evictedWhilePinned.removeAll()
    }
}

/// Track layout of the replay segments.
public struct ReplayTrackPlan: Equatable, Sendable {
    public var systemAudio: Bool
    public var microphone: Bool

    public init(systemAudio: Bool, microphone: Bool) {
        self.systemAudio = systemAudio
        self.microphone = microphone
    }
}

/// Stitches replay segments into one MP4 with ffmpeg: video is stream-copied (segments
/// begin on keyframes), audio is re-encoded to AAC so segment joins are gap-free.
///
/// Output audio layout:
///   track 0: game/system audio, with the mic mixed in when `mixMicIntoMain` is on.
///            The editor v0 only reads the first audio track (`0:a:0`).
///   track 1: raw microphone (only when captured), kept for future editor features.
public enum ClipAssembler {

    public static func concatList(_ urls: [URL]) -> String {
        urls.map { "file '" + $0.path.replacingOccurrences(of: "'", with: "'\\''") + "'\n" }.joined()
    }

    public static func arguments(listFile: URL, output: URL, plan: ReplayTrackPlan, mixMicIntoMain: Bool) -> [String] {
        var args = ["-hide_banner", "-loglevel", "error", "-y",
                    "-f", "concat", "-safe", "0", "-i", listFile.path]
        // Sources are PCM; resample with async fill so tiny gaps at segment joins don't drift.
        let fix = "aresample=async=1:first_pts=0"
        switch (plan.systemAudio, plan.microphone) {
        case (true, true):
            if mixMicIntoMain {
                let graph = "[0:a:0]\(fix)[sys];"
                    + "[0:a:1]\(fix),asplit=2[m1][m2];"
                    + "[m1]pan=stereo|c0=c0|c1=c0[mic];"
                    + "[sys][mic]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[mix]"
                args += ["-filter_complex", graph, "-map", "0:v:0", "-map", "[mix]", "-map", "[m2]"]
            } else {
                let graph = "[0:a:0]\(fix)[sys];[0:a:1]\(fix)[mic]"
                args += ["-filter_complex", graph, "-map", "0:v:0", "-map", "[sys]", "-map", "[mic]"]
            }
            args += ["-metadata:s:a:0", "title=Game" + (mixMicIntoMain ? " + mic" : ""),
                     "-metadata:s:a:1", "title=Microphone",
                     "-disposition:a:0", "default", "-disposition:a:1", "0"]
        case (true, false):
            args += ["-map", "0:v:0", "-map", "0:a:0", "-af", fix]
        case (false, true):
            args += ["-map", "0:v:0", "-map", "0:a:0", "-af", fix]
        case (false, false):
            args += ["-map", "0:v:0"]
        }
        args += ["-c:v", "copy"]
        if plan.systemAudio || plan.microphone {
            args += ["-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
        }
        args += ["-avoid_negative_ts", "make_zero", "-movflags", "+faststart", output.path]
        return args
    }

    public static func assemble(_ segments: [URL], plan: ReplayTrackPlan, mixMicIntoMain: Bool,
                                output: URL, tools: ToolLocations) async throws {
        guard let ffmpeg = tools.ffmpeg else { throw MediaError.toolMissing("ffmpeg") }
        guard !segments.isEmpty else { throw MediaError.conversionFailed("nothing buffered yet") }
        let list = output.deletingPathExtension().appendingPathExtension("txt")
        try concatList(segments).write(to: list, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: list) }
        let r = try await ProcessRunner.run(ffmpeg, arguments(listFile: list, output: output, plan: plan,
                                                              mixMicIntoMain: mixMicIntoMain),
                                            environment: Toolchain.childEnvironment(for: tools))
        guard r.status == 0 else {
            try? FileManager.default.removeItem(at: output)
            throw MediaError.conversionFailed(String(r.stderr.suffix(400)))
        }
    }
}
