import XCTest
@testable import ClipThatCore

final class ManifestTests: XCTestCase {
    private func session(_ clips: [Clip], music: String? = nil) -> Session {
        var s = Session(id: "s-test", title: "Test", createdAt: Date(timeIntervalSince1970: 0), clips: clips)
        s.settings.musicRelativePath = music
        return s
    }

    private func clip(_ path: String, media: Double, start: Double? = nil, length: Double? = nil) -> Clip {
        Clip(id: "id-" + path, relativePath: path, origin: .fileImport, capturedAt: Date(),
             mediaDuration: media, selectionStart: start, selectionDuration: length, hasAudio: true)
    }

    func testManifestMatchesContractKeys() throws {
        let data = try ManifestBuilder.manifestData(for: session([clip("clips/a.mp4", media: 31.5)]))
        let json = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(Set(json.keys), ["schema_version", "session_id", "style", "layout", "output", "clips", "music"])
        XCTAssertEqual(json["schema_version"] as? Int, 1)
        XCTAssertTrue(json["music"] is NSNull, "contract writes an explicit null")
        let output = try XCTUnwrap(json["output"] as? [String: Any])
        XCTAssertEqual(output["width"] as? Int, 1080)
        XCTAssertEqual(output["height"] as? Int, 1920)
        let first = try XCTUnwrap((json["clips"] as? [[String: Any]])?.first)
        XCTAssertEqual(Set(first.keys), ["id", "file", "start_seconds", "duration_seconds"])
        XCTAssertEqual(first["file"] as? String, "clips/a.mp4", "paths stay relative to the manifest")
        XCTAssertEqual(first["duration_seconds"] as? Double, 31.5)
    }

    func testMusicIsWrittenWhenSet() throws {
        let data = try ManifestBuilder.manifestData(for: session([clip("clips/a.mp4", media: 5)], music: "music/track.mp3"))
        let json = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let music = try XCTUnwrap(json["music"] as? [String: Any])
        XCTAssertEqual(music["file"] as? String, "music/track.mp3")
        XCTAssertEqual(music["volume"] as? Double, 0.15)
    }

    func testLongRecordingDefaultsToLast30Seconds() {
        let sel = ClipSelection.defaultSelection(mediaDuration: 600)
        XCTAssertEqual(sel.start, 570)
        XCTAssertEqual(sel.duration, 30)
        XCTAssertEqual(ClipSelection.defaultSelection(mediaDuration: 32.4).duration, 32.4)
    }

    func testSelectionIsClampedToEditorLimits() {
        let sel = ClipSelection.normalized(start: -5, duration: 500, mediaDuration: 200)
        XCTAssertEqual(sel.start, 0)
        XCTAssertEqual(sel.duration, RendererLimits.maxClipSeconds)
        let tail = ClipSelection.normalized(start: 28, duration: 10, mediaDuration: 30)
        XCTAssertLessThanOrEqual(tail.start + tail.duration, 30)
    }

    func testIssuesCatchMissingFilesAndEmptySessions() {
        XCTAssertFalse(ManifestBuilder.issues(for: session([])) { _ in true }.isEmpty)
        let issues = ManifestBuilder.issues(for: session([clip("clips/gone.mp4", media: 5)])) { _ in false }
        XCTAssertEqual(issues.first?.clipID, "id-clips/gone.mp4")
        XCTAssertTrue(ManifestBuilder.issues(for: session([clip("clips/a.mp4", media: 5)])) { _ in true }.isEmpty)
    }
}

final class RendererOutputTests: XCTestCase {
    func testParsesEditorSuccessLine() {
        let out = #"{"ok": true, "output": "/x/render.mp4", "clips": 3, "width": 1080, "height": 1920, "fps": 30}"#
        XCTAssertEqual(RendererOutput.success(stdout: out)?.clips, 3)
    }

    func testParsesEditorErrorLine() {
        let err = #"{"ok": false, "error": "Missing clip file: /x/a.mp4"}"#
        XCTAssertEqual(RendererOutput.errorMessage(stderr: err, status: 1), "Missing clip file: /x/a.mp4")
        XCTAssertEqual(RendererOutput.errorMessage(stderr: "", status: 2), "The editor exited with code 2.")
    }
}

final class PhraseSpotterTests: XCTestCase {
    func testFiresOncePerUtteranceAsTranscriptGrows() {
        var spotter = PhraseSpotter()
        XCTAssertFalse(spotter.process("oh my", at: 0))
        XCTAssertFalse(spotter.process("oh my god clip", at: 0.3))
        XCTAssertTrue(spotter.process("oh my god Clip that!", at: 0.6))
        XCTAssertFalse(spotter.process("oh my god Clip that! no way", at: 0.9), "same occurrence")
    }

    func testCooldownAndSecondTrigger() {
        var spotter = PhraseSpotter(cooldown: 2.5)
        XCTAssertTrue(spotter.process("clip that", at: 10))
        XCTAssertFalse(spotter.process("clip that clip that", at: 11), "within cooldown")
        XCTAssertTrue(spotter.process("clip that clip that clip that", at: 14))
    }

    func testResetForNewRecognitionTask() {
        var spotter = PhraseSpotter(cooldown: 0)
        XCTAssertTrue(spotter.process("clip that", at: 0))
        spotter.reset()
        XCTAssertTrue(spotter.process("clip that", at: 5))
    }

    func testIgnoresLookalikes() {
        var spotter = PhraseSpotter()
        XCTAssertFalse(spotter.process("the clipboard thing", at: 0))
        XCTAssertFalse(spotter.process("clip the other one", at: 1))
        XCTAssertTrue(spotter.process("CLIP. THAT.", at: 5))
    }
}

final class SegmentRingTests: XCTestCase {
    private func seg(_ n: Int, start: Double, length: Double = 2, sig: String = "a") -> ReplaySegment {
        ReplaySegment(url: URL(fileURLWithPath: "/tmp/seg\(n).mov"), start: start, end: start + length, signature: sig)
    }

    func testSelectsLast30SecondsOnSegmentBoundaries() {
        var ring = SegmentRing(retention: 40)
        for i in 0..<30 { _ = ring.append(seg(i, start: Double(i) * 2)) }   // 0...60 s
        let picked = ring.selection(endingAt: 60, duration: 30)
        XCTAssertEqual(picked.first?.start, 30)
        XCTAssertEqual(picked.last?.end, 60)
        XCTAssertEqual(picked.count, 15)
    }

    func testPrunesOldSegmentsButKeepsPinnedOnes() {
        var ring = SegmentRing(retention: 10)
        _ = ring.append(seg(0, start: 0))
        ring.pin([seg(0, start: 0).url])
        var deleted: [URL] = []
        for i in 1..<10 { deleted += ring.append(seg(i, start: Double(i) * 2)) }
        XCTAssertFalse(deleted.contains(seg(0, start: 0).url), "pinned file survives eviction")
        XCTAssertEqual(ring.unpin([seg(0, start: 0).url]), [seg(0, start: 0).url])
        XCTAssertLessThanOrEqual(ring.bufferedSeconds, 12)
    }

    func testDoesNotJoinAcrossTrackLayoutChanges() {
        var ring = SegmentRing(retention: 100)
        _ = ring.append(seg(0, start: 0, sig: "video+sys"))
        _ = ring.append(seg(1, start: 2, sig: "video+sys+mic"))
        _ = ring.append(seg(2, start: 4, sig: "video+sys+mic"))
        XCTAssertEqual(ring.selection(endingAt: 6, duration: 30).map(\.signature), ["video+sys+mic", "video+sys+mic"])
    }
}

final class FolderScannerTests: XCTestCase {
    func testOnlyNewStableFilesAreReported() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("scan-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        try Data("old".utf8).write(to: dir.appendingPathComponent("existing.mp4"))

        let scanner = FolderScanner(requiredStablePolls: 2)
        XCTAssertEqual(scanner.poll([dir]), [], "first poll records history")

        let new = dir.appendingPathComponent("Replay 2026-10-24 18-14-03.mkv")
        try Data(repeating: 1, count: 100).write(to: new)
        try Data("x".utf8).write(to: dir.appendingPathComponent("notes.txt"))
        try Data("x".utf8).write(to: dir.appendingPathComponent(".hidden.mp4"))
        XCTAssertEqual(scanner.poll([dir]), [])               // seen once
        try Data(repeating: 1, count: 200).write(to: new)    // still growing
        XCTAssertEqual(scanner.poll([dir]), [])
        XCTAssertEqual(scanner.poll([dir]), [])               // stable 1
        XCTAssertEqual(scanner.poll([dir]).map(\.lastPathComponent), [new.lastPathComponent])  // stable 2
        XCTAssertEqual(scanner.poll([dir]), [], "reported once")
    }

    func testCandidateFilter() {
        XCTAssertTrue(FolderScanner.isCandidate("clip.MP4"))
        XCTAssertTrue(FolderScanner.isCandidate("Replay.mkv"))
        XCTAssertFalse(FolderScanner.isCandidate("clip.mp4.part"))
        XCTAssertFalse(FolderScanner.isCandidate("~clip.mp4"))
        XCTAssertFalse(FolderScanner.isCandidate("thumb.png"))
    }
}

final class ClipAssemblerTests: XCTestCase {
    func testMixedPlanKeepsRawMicAsSecondTrack() {
        let args = ClipAssembler.arguments(listFile: URL(fileURLWithPath: "/t/l.txt"),
                                           output: URL(fileURLWithPath: "/t/o.mp4"),
                                           plan: ReplayTrackPlan(systemAudio: true, microphone: true),
                                           mixMicIntoMain: true)
        XCTAssertTrue(args.contains("[mix]"))
        XCTAssertTrue(args.contains("[m2]"))
        XCTAssertEqual(args.last, "/t/o.mp4")
        XCTAssertTrue(args.contains("copy"), "video is stream-copied")
    }

    func testConcatListEscapesQuotes() {
        let list = ClipAssembler.concatList([URL(fileURLWithPath: "/a/it's.mov")])
        XCTAssertEqual(list, "file '/a/it'\\''s.mov'\n")
    }
}

final class SessionStoreTests: XCTestCase {
    func testCreateSaveLoadAndUniqueNames() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("store-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = SessionStore(root: root)
        var session = try store.create(title: "Ranked night")
        let a = try store.uniqueDestination(in: session, folder: "clips", baseName: "replay voice!", ext: "MP4")
        try Data().write(to: a.url)
        let b = try store.uniqueDestination(in: session, folder: "clips", baseName: "replay voice!", ext: "mp4")
        XCTAssertEqual(a.relativePath, "clips/replay-voice.mp4")
        XCTAssertEqual(b.relativePath, "clips/replay-voice-2.mp4")
        session.clips.append(Clip(relativePath: a.relativePath, origin: .replay, trigger: .voice,
                                  capturedAt: Date(), mediaDuration: 31, triggerOffset: 29.5, hasAudio: true))
        try store.save(session)
        let loaded = store.loadAll()
        XCTAssertEqual(loaded.first?.title, "Ranked night")
        XCTAssertEqual(loaded.first?.clips.first?.trigger, .voice)
        XCTAssertEqual(loaded.first?.clips.first?.sourceLabel, "Replay · Voice")
    }
}

/// End-to-end: real ffmpeg + the real clipthat_editor from this repo. Skips when the
/// tools aren't installed. This is desktop acceptance test 4 (three MP4s -> one 9:16 MP4).
final class EditorIntegrationTests: XCTestCase {
    func testThreeClipsRenderToPortraitThroughTheRealEditor() async throws {
        // desktop/Core/Tests/ClipThatCoreTests/CoreTests.swift -> repo root
        let repoRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let tools = Toolchain.locate(bundledEditor: repoRoot)
        try requireTools(tools)

        let root = FileManager.default.temporaryDirectory.appendingPathComponent("e2e-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = SessionStore(root: root)
        var session = try store.create(title: "E2E")

        let sources = root.appendingPathComponent("sources")
        try FileManager.default.createDirectory(at: sources, withIntermediateDirectories: true)
        for (i, color) in ["blue", "red", "green"].enumerated() {
            let file = sources.appendingPathComponent("moment-\(i).mp4")
            var args = ["-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=\(color):s=640x360:r=30:d=2"]
            if i != 1 { args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", "-shortest"] }
            args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", file.path]
            let r = try await ProcessRunner.run(tools.ffmpeg!, args)
            XCTAssertEqual(r.status, 0, r.stderr)
            let clip = try await ClipImporter.importFile(file, into: session, store: store, tools: tools,
                                                         origin: .fileImport, importedFrom: nil)
            session.clips.append(clip)
        }
        session.settings.width = 360
        session.settings.height = 640
        try store.save(session)

        let (result, record) = try await Renderer.render(session: session, store: store, tools: tools)
        let info = try await MediaProbe.probe(result.output, tools: tools)
        XCTAssertEqual(info.width, 360)
        XCTAssertEqual(info.height, 640)
        XCTAssertTrue(info.hasAudio)
        XCTAssertGreaterThan(info.duration, 5.5)
        XCTAssertTrue(record.relativePath.hasPrefix("renders/"))
    }

    /// Suggested trim on a replay-style clip: real moment at 20 s, "Clip that" at 24 s,
    /// a decoy burst after the trigger at 28 s. The trigger-aware analyzer must pick 20 s.
    func testSuggestedTrimRespectsTrigger() async throws {
        let repoRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let tools = Toolchain.locate(bundledEditor: repoRoot)
        try requireTools(tools)
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("analyze-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let clip = dir.appendingPathComponent("replay.mp4")
        let moments = [20.0, 28.0]
        let boxes = moments.map { "drawbox=enable='between(t,\($0),\($0 + 0.6))':color=red:t=fill" }.joined(separator: ",")
        let envelope = moments.map { "between(t,\($0),\($0 + 0.6))" }.joined(separator: "+")
        let r = try await ProcessRunner.run(tools.ffmpeg!, [
            "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x203050:s=320x180:r=30:d=31.5",
            "-f", "lavfi", "-i", "anoisesrc=d=31.5:a=0.9:r=48000",
            "-filter_complex", "[0:v]\(boxes)[v];[1:a]volume='if(\(envelope),1,0.02)':eval=frame[a]",
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "31.5", clip.path,
        ])
        XCTAssertEqual(r.status, 0, r.stderr)
        let s = try await ClipAnalyzer.suggest(for: clip, length: 8, triggerOffset: 24, tools: tools)
        XCTAssertLessThanOrEqual(s.suggestedStart, 20)
        XCTAssertGreaterThanOrEqual(s.suggestedStart + s.suggestedDuration, 20.6)
        XCTAssertLessThanOrEqual(s.suggestedStart + s.suggestedDuration, 25.51)
    }

    /// Skips locally when tools are missing; fails in CI (CLIPTHAT_REQUIRE_E2E=1) so a green
    /// run always means the end-to-end tests really ran.
    private func requireTools(_ tools: ToolLocations) throws {
        if ProcessInfo.processInfo.environment["CLIPTHAT_REQUIRE_E2E"] == "1" {
            guard tools.isComplete else {
                XCTFail("CLIPTHAT_REQUIRE_E2E=1 but missing: \(tools.missing)")
                throw XCTSkip("missing tools")
            }
        }
        try XCTSkipUnless(tools.isComplete, "needs python3, ffmpeg, ffprobe and clipthat_editor: missing \(tools.missing)")
    }
}
