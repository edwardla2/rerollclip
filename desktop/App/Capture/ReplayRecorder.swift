import AppKit
import AVFoundation
import ClipThatCore
import CoreMedia
import ScreenCaptureKit

struct ReplayConfiguration: Equatable {
    var bufferSeconds: Double
    var postRollSeconds: Double
    var fps: Int
    var maxHeight: Int
    var includeMicrophone: Bool
    var excludedBundleIDs: [String]
}

struct SavedReplay {
    var url: URL
    var triggerOffset: Double
    var plan: ReplayTrackPlan
    var capturedAt: Date
}

enum ReplayError: LocalizedError {
    case notRunning
    case paused
    case noDisplay
    case permissionDenied
    case nothingBuffered
    case writer(String)

    var errorDescription: String? {
        switch self {
        case .notRunning: return "The replay buffer is off. Turn it on to save clips."
        case .paused: return "Replay is paused. Resume it to save clips."
        case .noDisplay: return "No display available to record."
        case .permissionDenied:
            return "Screen Recording permission is needed. Allow Clip That in System Settings → Privacy & Security → Screen & System Audio Recording, then turn the replay buffer on again."
        case .nothingBuffered: return "Nothing has been buffered yet. Try again in a moment."
        case .writer(let detail): return "Recording error: \(detail)"
        }
    }
}

/// Opt-in rolling replay buffer.
///
/// ScreenCaptureKit delivers screen frames, system audio and (macOS 15+) microphone
/// samples. They're encoded into ~2 s segment files (H.264 video starting on a keyframe,
/// PCM audio) in a private cache folder; segments older than the buffer length are
/// deleted as new ones finish. "Clip that" waits a short post-roll, closes the current
/// segment, and stitches the segments covering the last N seconds into one MP4.
///
/// Privacy: nothing is captured until `start` is called; the buffer folder is wiped on
/// stop, on capture errors, and at launch. Clip That's own windows and any apps on the
/// exclusion list are left out of the capture.
final class ReplayRecorder: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    enum Status: Equatable {
        case off
        case starting
        case buffering
        case paused
        case failed(String)
    }

    /// Called on the main thread with the status and seconds currently buffered.
    var onStatusChange: ((Status, Double) -> Void)?

    static let segmentSeconds = 2.0

    private let queue = DispatchQueue(label: "now.kova.clipthat.replay", qos: .userInitiated)

    // Everything below is only touched on `queue`.
    private var stream: SCStream?
    private var displayID: CGDirectDisplayID = CGMainDisplayID()
    private var config = ReplayConfiguration(bufferSeconds: 30, postRollSeconds: 1.5, fps: 60, maxHeight: 1080,
                                             includeMicrophone: false, excludedBundleIDs: [])
    private var ring = SegmentRing(retention: 40)
    private var current: SegmentWriter?
    private var finishing: [ObjectIdentifier: SegmentWriter] = [:]
    private var flushWaiters: [() -> Void] = []
    private var plan: ReplayTrackPlan?
    private var firstVideoTime: Double?
    private var systemFormat: CMFormatDescription?
    private var micFormat: CMFormatDescription?
    private var videoWidth = 0
    private var videoHeight = 0
    private var runID = ""
    private var runDirectory: URL?
    private var segmentCounter = 0
    private var running = false
    private var paused = false
    private var status: Status = .off

    // MARK: Lifecycle

    func start(_ newConfig: ReplayConfiguration) async throws {
        await shutdown(status: .off)
        publishFromOutside(.starting)

        let content: SCShareableContent
        do {
            content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        } catch {
            publishFromOutside(.failed(ReplayError.permissionDenied.localizedDescription))
            throw ReplayError.permissionDenied
        }
        let mainID = CGMainDisplayID()
        guard let display = content.displays.first(where: { $0.displayID == mainID }) ?? content.displays.first else {
            publishFromOutside(.failed(ReplayError.noDisplay.localizedDescription))
            throw ReplayError.noDisplay
        }

        let filter = Self.makeFilter(display: display, content: content, excluded: newConfig.excludedBundleIDs)
        let info = SCShareableContent.info(for: filter)
        let scale = Double(info.pointPixelScale)
        var width = Int((Double(info.contentRect.width) * scale).rounded())
        var height = Int((Double(info.contentRect.height) * scale).rounded())
        if height > newConfig.maxHeight {
            width = Int((Double(width) * Double(newConfig.maxHeight) / Double(height)).rounded())
            height = newConfig.maxHeight
        }
        width -= width % 2
        height -= height % 2

        let sc = SCStreamConfiguration()
        sc.width = width
        sc.height = height
        sc.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(newConfig.fps))
        sc.pixelFormat = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
        sc.showsCursor = true
        sc.queueDepth = 8
        sc.capturesAudio = true
        sc.sampleRate = 48_000
        sc.channelCount = 2
        sc.excludesCurrentProcessAudio = true
        sc.captureMicrophone = newConfig.includeMicrophone

        let newStream = SCStream(filter: filter, configuration: sc, delegate: self)
        let directory = try Self.makeRunDirectory()
        do {
            try newStream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
            try newStream.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
            if newConfig.includeMicrophone {
                try newStream.addStreamOutput(self, type: .microphone, sampleHandlerQueue: queue)
            }
        } catch {
            try? FileManager.default.removeItem(at: directory)
            publishFromOutside(.failed(error.localizedDescription))
            throw ReplayError.writer(error.localizedDescription)
        }

        queue.sync {
            stream = newStream
            displayID = display.displayID
            config = newConfig
            videoWidth = width
            videoHeight = height
            runID = UUID().uuidString.prefix(8).lowercased()
            runDirectory = directory
            segmentCounter = 0
            plan = nil
            firstVideoTime = nil
            systemFormat = nil
            micFormat = nil
            ring = SegmentRing(retention: newConfig.bufferSeconds + newConfig.postRollSeconds + 3 * Self.segmentSeconds)
            paused = false
            running = true
        }

        do {
            try await newStream.startCapture()
        } catch {
            await shutdown(status: .failed(error.localizedDescription))
            throw ReplayError.writer(error.localizedDescription)
        }
        publishFromOutside(.buffering)
    }

    /// Stops capture and wipes the buffer from disk.
    func stop() async {
        await shutdown(status: .off)
    }

    func setPaused(_ value: Bool) {
        queue.async {
            guard self.running else { return }
            self.paused = value
            if value, let writer = self.current {
                self.current = nil
                self.finish(writer, at: Self.hostNow())
            }
            self.publish(value ? .paused : .buffering)
        }
    }

    /// Re-applies the exclusion list, e.g. after an excluded app launches.
    func refreshExclusions(_ bundleIDs: [String]) async {
        let (activeStream, display): (SCStream?, CGDirectDisplayID) = queue.sync {
            config.excludedBundleIDs = bundleIDs
            return (stream, displayID)
        }
        guard let activeStream,
              let content = try? await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true),
              let scDisplay = content.displays.first(where: { $0.displayID == display }) else { return }
        try? await activeStream.updateContentFilter(Self.makeFilter(display: scDisplay, content: content, excluded: bundleIDs))
    }

    private func shutdown(status newStatus: Status) async {
        let activeStream: SCStream? = queue.sync {
            let s = stream
            stream = nil
            running = false
            return s
        }
        if let activeStream { try? await activeStream.stopCapture() }
        queue.sync {
            self.wipeBuffer()
            self.publish(newStatus)
        }
    }

    /// On `queue`.
    private func wipeBuffer() {
        current?.cancel()
        current = nil
        for writer in finishing.values { writer.cancel() }
        finishing.removeAll()
        ring.removeAll()
        if let runDirectory { try? FileManager.default.removeItem(at: runDirectory) }
        runDirectory = nil
        plan = nil
        firstVideoTime = nil
        let waiters = flushWaiters
        flushWaiters = []
        waiters.forEach { $0() }   // they find an empty ring and report nothingBuffered
    }

    // MARK: Saving a clip

    /// Saves roughly the last `bufferSeconds` plus a short post-roll (so the moment you
    /// react to isn't cut off mid-sentence). Returns a temporary MP4 the caller must move.
    func saveClip(tools: ToolLocations, mixMicIntoMain: Bool) async throws -> SavedReplay {
        let triggerTime = Self.hostNow().seconds
        let capturedAt = Date()
        let (post, buffer, isRunning, isPaused) = queue.sync {
            (config.postRollSeconds, config.bufferSeconds, running, paused)
        }
        guard isRunning else { throw ReplayError.notRunning }
        guard !isPaused else { throw ReplayError.paused }

        try await Task.sleep(nanoseconds: UInt64(max(0, post) * 1_000_000_000))
        let (segments, plan) = try await flushAndSelect(duration: buffer + post)
        defer { release(segments) }

        let output = try Self.pendingDirectory().appendingPathComponent("replay-\(UUID().uuidString.prefix(8)).mp4")
        try await ClipAssembler.assemble(segments.map(\.url), plan: plan, mixMicIntoMain: mixMicIntoMain,
                                         output: output, tools: tools)
        let start = segments.first?.start ?? triggerTime
        return SavedReplay(url: output, triggerOffset: max(0, triggerTime - start), plan: plan, capturedAt: capturedAt)
    }

    private func flushAndSelect(duration: Double) async throws -> ([ReplaySegment], ReplayTrackPlan) {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                guard self.running else {
                    continuation.resume(throwing: ReplayError.notRunning)
                    return
                }
                let end = Self.hostNow()
                let deliver = {
                    let picked = self.ring.selection(endingAt: end.seconds, duration: duration)
                    guard !picked.isEmpty, let plan = self.plan else {
                        continuation.resume(throwing: ReplayError.nothingBuffered)
                        return
                    }
                    self.ring.pin(picked.map(\.url))
                    continuation.resume(returning: (picked, plan))
                }
                if let writer = self.current {
                    self.current = nil
                    self.finish(writer, at: end)
                }
                if self.finishing.isEmpty { deliver() } else { self.flushWaiters.append(deliver) }
            }
        }
    }

    private func release(_ segments: [ReplaySegment]) {
        queue.async {
            for url in self.ring.unpin(segments.map(\.url)) { try? FileManager.default.removeItem(at: url) }
        }
    }

    // MARK: SCStreamOutput (on `queue`)

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard running, CMSampleBufferIsValid(sampleBuffer) else { return }
        switch type {
        case .screen:
            if !paused { handleVideo(sampleBuffer) }
        case .audio:
            handleAudio(sampleBuffer, isMic: false)
        case .microphone:
            handleAudio(sampleBuffer, isMic: true)
        @unknown default:
            break
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        queue.async {
            self.stream = nil
            self.running = false
            self.wipeBuffer()
            self.publish(.failed("Recording stopped: \(error.localizedDescription)"))
        }
    }

    private func handleVideo(_ sampleBuffer: CMSampleBuffer) {
        guard Self.isCompleteFrame(sampleBuffer) else { return }
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let t = pts.seconds

        // Fix the track layout once per run, after audio formats have shown up (or 1.5 s).
        // Every segment in a run then has identical tracks, so any run can be stitched.
        if plan == nil {
            if firstVideoTime == nil { firstVideoTime = t }
            let wantMic = config.includeMicrophone
            let haveAll = systemFormat != nil && (!wantMic || micFormat != nil)
            guard haveAll || t - (firstVideoTime ?? t) > 1.5 else { return }
            plan = ReplayTrackPlan(systemAudio: systemFormat != nil, microphone: wantMic && micFormat != nil)
        }

        if let writer = current, t - writer.startSeconds >= Self.segmentSeconds {
            current = nil
            finish(writer, at: pts)
        }
        if current == nil {
            do {
                current = try makeWriter(start: pts)
            } catch {
                fail(error)
                return
            }
        }
        current?.appendVideo(sampleBuffer)
    }

    private func handleAudio(_ sampleBuffer: CMSampleBuffer, isMic: Bool) {
        if isMic {
            if micFormat == nil { micFormat = CMSampleBufferGetFormatDescription(sampleBuffer) }
        } else if systemFormat == nil {
            systemFormat = CMSampleBufferGetFormatDescription(sampleBuffer)
        }
        guard !paused else { return }
        current?.appendAudio(sampleBuffer, isMic: isMic)
    }

    private func makeWriter(start: CMTime) throws -> SegmentWriter {
        guard let runDirectory, let plan else { throw ReplayError.notRunning }
        segmentCounter += 1
        let url = runDirectory.appendingPathComponent(String(format: "seg-%06d.mov", segmentCounter))
        return try SegmentWriter(url: url, start: start, width: videoWidth, height: videoHeight, fps: config.fps,
                                 systemFormat: plan.systemAudio ? systemFormat : nil,
                                 micFormat: plan.microphone ? micFormat : nil)
    }

    private func finish(_ writer: SegmentWriter, at end: CMTime) {
        let key = ObjectIdentifier(writer)
        finishing[key] = writer
        let signature = runID + "-s\(plan?.systemAudio == true ? 1 : 0)m\(plan?.microphone == true ? 1 : 0)"
        writer.finish(at: end) { [weak self] ok in
            guard let self else { return }
            self.queue.async {
                guard self.finishing.removeValue(forKey: key) != nil else { return }   // wiped meanwhile
                if ok, self.runDirectory != nil {
                    let segment = ReplaySegment(url: writer.url, start: writer.startSeconds, end: end.seconds,
                                                signature: signature)
                    for url in self.ring.append(segment) { try? FileManager.default.removeItem(at: url) }
                } else {
                    try? FileManager.default.removeItem(at: writer.url)
                }
                if self.finishing.isEmpty {
                    let waiters = self.flushWaiters
                    self.flushWaiters = []
                    waiters.forEach { $0() }
                }
                if self.running { self.publish(self.paused ? .paused : .buffering) }
            }
        }
    }

    private func fail(_ error: Error) {
        running = false
        let activeStream = stream
        stream = nil
        wipeBuffer()
        publish(.failed(error.localizedDescription))
        Task { try? await activeStream?.stopCapture() }
    }

    // MARK: Status

    /// On `queue`.
    private func publish(_ newStatus: Status) {
        status = newStatus
        let seconds = min(ring.bufferedSeconds, config.bufferSeconds)
        let callback = onStatusChange
        DispatchQueue.main.async { callback?(newStatus, seconds) }
    }

    private func publishFromOutside(_ newStatus: Status) {
        queue.async { self.publish(newStatus) }
    }

    // MARK: Helpers

    static func hostNow() -> CMTime {
        CMClockGetTime(CMClockGetHostTimeClock())
    }

    private static func isCompleteFrame(_ sampleBuffer: CMSampleBuffer) -> Bool {
        guard let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false)
                as? [[SCStreamFrameInfo: Any]],
              let raw = attachments.first?[.status] as? Int,
              let frameStatus = SCFrameStatus(rawValue: raw) else { return false }
        return frameStatus == .complete
    }

    private static func makeFilter(display: SCDisplay, content: SCShareableContent, excluded: [String]) -> SCContentFilter {
        let own = Bundle.main.bundleIdentifier
        let apps = content.applications.filter { app in
            app.bundleIdentifier == own || excluded.contains(app.bundleIdentifier)
        }
        return SCContentFilter(display: display, excludingApplications: apps, exceptingWindows: [])
    }

    static var cacheRoot: URL {
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return caches.appendingPathComponent("ClipThat", isDirectory: true)
    }

    private static func makeRunDirectory() throws -> URL {
        let dir = cacheRoot.appendingPathComponent("Replay", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static func pendingDirectory() throws -> URL {
        let dir = cacheRoot.appendingPathComponent("Pending", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// Called at launch: removes buffers left behind by a crash or force-quit.
    static func wipeStaleBuffers() {
        try? FileManager.default.removeItem(at: cacheRoot.appendingPathComponent("Replay", isDirectory: true))
        try? FileManager.default.removeItem(at: cacheRoot.appendingPathComponent("Pending", isDirectory: true))
    }
}

/// One segment file: H.264 video (first frame is a keyframe) + PCM audio tracks in a .mov.
/// PCM keeps segment joins sample-accurate; the final clip re-encodes audio to AAC.
final class SegmentWriter {
    let url: URL
    let start: CMTime
    var startSeconds: Double { start.seconds }

    private let writer: AVAssetWriter
    private let video: AVAssetWriterInput
    private let system: AVAssetWriterInput?
    private let mic: AVAssetWriterInput?

    init(url: URL, start: CMTime, width: Int, height: Int, fps: Int,
         systemFormat: CMFormatDescription?, micFormat: CMFormatDescription?) throws {
        let assetWriter = try AVAssetWriter(outputURL: url, fileType: .mov)
        let bitrate = min(max(Int(Double(width * height * fps) * 0.1), 4_000_000), 40_000_000)
        let compression: [String: Any] = [
            AVVideoAverageBitRateKey: bitrate,
            AVVideoExpectedSourceFrameRateKey: fps,
            AVVideoMaxKeyFrameIntervalKey: fps * 2,
            AVVideoMaxKeyFrameIntervalDurationKey: 2.0,
            AVVideoAllowFrameReorderingKey: false,
            AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
        ]
        let videoInput = AVAssetWriterInput(mediaType: .video, outputSettings: [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: compression,
        ])
        videoInput.expectsMediaDataInRealTime = true
        guard assetWriter.canAdd(videoInput) else { throw ReplayError.writer("can't add the video track") }
        assetWriter.add(videoInput)
        let systemInput = try Self.addAudioInput(to: assetWriter, format: systemFormat)
        let micInput = try Self.addAudioInput(to: assetWriter, format: micFormat)

        self.url = url
        self.start = start
        self.writer = assetWriter
        self.video = videoInput
        self.system = systemInput
        self.mic = micInput

        guard assetWriter.startWriting() else {
            throw ReplayError.writer(assetWriter.error?.localizedDescription ?? "couldn't start writing")
        }
        assetWriter.startSession(atSourceTime: start)
    }

    func appendVideo(_ sampleBuffer: CMSampleBuffer) {
        guard writer.status == .writing, video.isReadyForMoreMediaData else { return }
        video.append(sampleBuffer)
    }

    func appendAudio(_ sampleBuffer: CMSampleBuffer, isMic: Bool) {
        guard writer.status == .writing, let input = isMic ? mic : system, input.isReadyForMoreMediaData else { return }
        input.append(sampleBuffer)
    }

    func finish(at end: CMTime, completion: @escaping (Bool) -> Void) {
        guard writer.status == .writing, CMTimeCompare(end, start) > 0 else {
            cancel()
            completion(false)
            return
        }
        writer.endSession(atSourceTime: end)
        video.markAsFinished()
        system?.markAsFinished()
        mic?.markAsFinished()
        let assetWriter = writer
        assetWriter.finishWriting {
            completion(assetWriter.status == .completed)
        }
    }

    func cancel() {
        if writer.status == .writing { writer.cancelWriting() }
        try? FileManager.default.removeItem(at: url)
    }

    private static func addAudioInput(to writer: AVAssetWriter, format: CMFormatDescription?) throws -> AVAssetWriterInput? {
        guard let format, let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(format)?.pointee else { return nil }
        let channels = Int(max(1, min(asbd.mChannelsPerFrame, 2)))
        var layout = AudioChannelLayout()
        layout.mChannelLayoutTag = channels == 1 ? kAudioChannelLayoutTag_Mono : kAudioChannelLayoutTag_Stereo
        let layoutData = Data(bytes: &layout, count: MemoryLayout<AudioChannelLayout>.size)
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: asbd.mSampleRate,
            AVNumberOfChannelsKey: channels,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
            AVChannelLayoutKey: layoutData,
        ]
        let input = AVAssetWriterInput(mediaType: .audio, outputSettings: settings, sourceFormatHint: format)
        input.expectsMediaDataInRealTime = true
        guard writer.canAdd(input) else { throw ReplayError.writer("can't add an audio track") }
        writer.add(input)
        return input
    }
}
