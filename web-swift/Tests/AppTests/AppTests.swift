import Foundation
import XCTVapor
@testable import App

/// Parity with web/tests/test_server.py: the Vapor backend must behave like the
/// prototype it replaces, endpoint for endpoint.
final class AppTests: XCTestCase {
    var app: Application!
    var runtime: URL!

    /// web-swift/Tests/AppTests/AppTests.swift -> repository root
    static let repoRoot: String = {
        var url = URL(fileURLWithPath: #filePath)
        for _ in 0..<4 { url.deleteLastPathComponent() }
        return url.path + "/"
    }()

    func makeConfig(maxUploadBytes: Int = 250 * 1024 * 1024) -> ClipThatConfig {
        ClipThatConfig(staticDirectory: Self.repoRoot + "web/static/",
                       runtimeDirectory: runtime.path,
                       editorRoot: Self.repoRoot,
                       pythonCommand: ["/usr/bin/env", "python3"],
                       maxUploadBytes: maxUploadBytes,
                       renderTimeoutSeconds: 300,
                       retentionSeconds: 24 * 3600,
                       databasePath: nil)
    }

    func start(maxUploadBytes: Int = 250 * 1024 * 1024) async throws {
        app = try await Application.make(.testing)
        try await configure(app, config: makeConfig(maxUploadBytes: maxUploadBytes))
    }

    override func setUp() async throws {
        runtime = FileManager.default.temporaryDirectory.appendingPathComponent("clipthat-web-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: runtime, withIntermediateDirectories: true)
    }

    override func tearDown() async throws {
        try await app?.asyncShutdown()
        app = nil
        try? FileManager.default.removeItem(at: runtime)
    }

    static func newProjectID() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
    }

    // MARK: Pages and health

    func testHomeStudioAndHealth() async throws {
        try await start()
        try await app.test(.GET, "/") { res async in
            XCTAssertEqual(res.status, .ok)
            XCTAssertTrue(res.body.string.contains("Clip That"))
        }
        try await app.test(.GET, "studio") { res async in
            XCTAssertEqual(res.status, .ok)
            XCTAssertTrue(res.body.string.contains("id=\"export-open\""))
        }
        try await app.test(.GET, "assets/tokens.css") { res async in
            XCTAssertEqual(res.status, .ok)
        }
        try await app.test(.GET, "api/health") { res async throws in
            let json = try JSONSerialization.jsonObject(with: Data(res.body.readableBytesView)) as? [String: Any]
            XCTAssertEqual(json?["cloud_saving"] as? Bool, false)
        }
    }

    /// Guardrails: the landing page may only claim what ships.
    func testLandingPageClaims() async throws {
        try await start()
        try await app.test(.GET, "/") { res async in
            let page = res.body.string
            XCTAssertTrue(page.contains("macOS 15 or later"))
            XCTAssertTrue(page.contains("plus about 1.5 seconds after"))
            XCTAssertTrue(page.contains("signed, notarized installer is not available yet"))
            XCTAssertTrue(page.contains("id=\"beta-form\""))
            XCTAssertFalse(page.contains("id=\"download-desktop\""))
            XCTAssertTrue(page.contains("AI highlight detection or beat sync yet"))
            XCTAssertTrue(page.contains("No automatic upload"))
        }
    }

    // MARK: Validation and security

    func testRejectsBadProjectAndManifest() async throws {
        try await start()
        try await app.test(.POST, "api/projects/not-a-project/clips") { res async in
            XCTAssertEqual(res.status, .badRequest)
        }
        let id = Self.newProjectID()
        try await app.test(.POST, "api/projects/\(id)/render", beforeRequest: { req in
            try req.content.encode(["clips": [["file": "../not-allowed.mp4", "start_seconds": 0, "duration_seconds": 1]]] as [String: [[String: AnyCodableValue]]])
        }) { res async in
            XCTAssertEqual(res.status, .badRequest)
        }
        try await app.test(.POST, "api/projects/\(id)/render", beforeRequest: { req in
            try req.content.encode(["clips": [["file": .string(Self.newProjectID() + ".mp4"), "start_seconds": 0, "duration_seconds": 1]]] as [String: [[String: AnyCodableValue]]])
        }) { res async in
            XCTAssertEqual(res.status, .notFound)
        }
    }

    func testUploadExtensionAndSizeLimits() async throws {
        try await start(maxUploadBytes: 4)
        let id = Self.newProjectID()
        try await app.test(.POST, "api/projects/\(id)/clips", beforeRequest: { req in
            try req.content.encode(UploadForm(file: File(data: "text", filename: "fake.txt")), as: .formData)
        }) { res async in
            XCTAssertEqual(res.status, .unsupportedMediaType)
        }
        try await app.test(.POST, "api/projects/\(id)/clips", beforeRequest: { req in
            try req.content.encode(UploadForm(file: File(data: "123456", filename: "test.mp4")), as: .formData)
        }) { res async in
            XCTAssertEqual(res.status, .payloadTooLarge)
        }
        let leftovers = (try? FileManager.default.contentsOfDirectory(atPath: runtime.appendingPathComponent(id).path)) ?? []
        XCTAssertTrue(leftovers.filter { $0.hasSuffix(".mp4") }.isEmpty)
    }

    func testUploadNamesAreValidated() {
        XCTAssertTrue(ProjectController.isUploadName(Self.newProjectID() + ".mp4"))
        XCTAssertFalse(ProjectController.isUploadName("../x.mp4"))
        XCTAssertFalse(ProjectController.isUploadName(Self.newProjectID() + ".exe"))
        XCTAssertFalse(ProjectController.isUploadName(Self.newProjectID() + ".mp4.mp4"))
        XCTAssertFalse(ProjectController.isClipID("../x"))
        XCTAssertTrue(ProjectController.isClipID("item_1-a"))
    }

    // MARK: Beta interest

    func testBetaInterestStorage() async throws {
        try await start()
        func post(_ body: [String: AnyCodableValue]) async throws -> HTTPStatus {
            var status = HTTPStatus.internalServerError
            try await app.test(.POST, "api/beta-interest", beforeRequest: { req in
                try req.content.encode(body)
            }) { res async in status = res.status }
            return status
        }
        let noConsent = try await post(["email": "a@example.com", "consent": false])
        XCTAssertEqual(noConsent, .badRequest)
        let invalid = try await post(["email": "not valid", "consent": true])
        XCTAssertEqual(invalid, .unprocessableEntity)
        let spam = try await post(["email": "spam@example.com", "consent": true, "website": "https://spam.example"])
        XCTAssertEqual(spam, .ok)
        let first = try await post(["email": "Test@Example.Com", "consent": true])
        XCTAssertEqual(first, .ok)
        let duplicate = try await post(["email": "test@example.com", "consent": true])
        XCTAssertEqual(duplicate, .ok)
        let stored = try await BetaInterest.query(on: app.db).all().compactMap(\.id)
        XCTAssertEqual(stored, ["test@example.com"])
    }

    func testEmailRule() {
        XCTAssertTrue(BetaInterestController.isEmail("a@b.co"))
        XCTAssertFalse(BetaInterestController.isEmail("a@b.c"))
        XCTAssertFalse(BetaInterestController.isEmail("a b@c.de"))
        XCTAssertFalse(BetaInterestController.isEmail("@c.de"))
        XCTAssertFalse(BetaInterestController.isEmail("a@.de"))
    }

    // MARK: End to end (needs ffmpeg + python3)

    func testUploadRenderDownloadEndToEnd() async throws {
        try Self.requireTools()
        try await start()
        let id = Self.newProjectID()
        var uploaded: [String] = []
        for (name, color, audio) in [("a.mp4", "blue", true), ("b.mov", "red", false)] {
            let path = runtime.appendingPathComponent("src-" + name)
            try Self.makeClip(path, color: color, audio: audio)
            let data = try Data(contentsOf: path)
            try await app.test(.POST, "api/projects/\(id)/clips", beforeRequest: { req in
                try req.content.encode(UploadForm(file: File(data: ByteBuffer(bytes: data), filename: name)), as: .formData)
            }) { res async throws in
                XCTAssertEqual(res.status, .ok, res.body.string)
                uploaded.append(try res.content.decode(UploadResult.self).file)
            }
        }
        let request = RenderRequest(clips: [
            RenderClip(id: "item1", file: uploaded[0], startSeconds: 0.5, durationSeconds: 1.2),
            RenderClip(id: "item2", file: uploaded[1], startSeconds: 0, durationSeconds: 1.0),
            RenderClip(id: nil, file: uploaded[0], startSeconds: 0, durationSeconds: 0.8),
        ], style: "clean", layout: "center_crop", size: "480")
        var url = ""
        try await app.test(.POST, "api/projects/\(id)/render", beforeRequest: { req in
            try req.content.encode(request)
        }) { res async throws in
            XCTAssertEqual(res.status, .ok, res.body.string)
            url = try res.content.decode(RenderResult.self).url
        }
        let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: runtime.appendingPathComponent(id).appendingPathComponent("manifest.json"))) as? [String: Any]
        let ids = (manifest?["clips"] as? [[String: Any]])?.compactMap { $0["id"] as? String }
        XCTAssertEqual(ids, ["item1", "item2", "clip-3"])

        try await app.test(.GET, url) { res async throws in
            XCTAssertEqual(res.status, .ok)
            XCTAssertEqual(res.headers.contentType?.description, "video/mp4")
            let out = runtime.appendingPathComponent("out.mp4")
            try Data(res.body.readableBytesView).write(to: out)
            let probe = try Self.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "csv=p=0", out.path])
            XCTAssertTrue(probe.contains("video,480,852"), probe)
            XCTAssertTrue(probe.contains("audio"), probe)
        }
    }

    func testAnalyzeFindsPlantedMoment() async throws {
        try Self.requireTools()
        try await start()
        let id = Self.newProjectID()
        // 20 s clip: quiet noise + static frame, with a loud burst and a red flash at 13 s.
        let src = runtime.appendingPathComponent("moment.mp4")
        try Self.run(["ffmpeg", "-loglevel", "error", "-y",
                      "-f", "lavfi", "-i", "color=c=0x203050:s=320x180:r=30:d=20",
                      "-f", "lavfi", "-i", "anoisesrc=d=20:a=0.9:r=48000",
                      "-filter_complex", "[0:v]drawbox=enable='between(t,13,13.6)':color=red:t=fill[v];[1:a]volume='if(between(t,13,13.6),1,0.02)':eval=frame[a]",
                      "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "20", src.path])
        let data = try Data(contentsOf: src)
        var uploaded = ""
        try await app.test(.POST, "api/projects/\(id)/clips", beforeRequest: { req in
            try req.content.encode(UploadForm(file: File(data: ByteBuffer(bytes: data), filename: "moment.mp4")), as: .formData)
        }) { res async throws in uploaded = try res.content.decode(UploadResult.self).file }
        try await app.test(.POST, "api/projects/\(id)/clips/\(uploaded)/analyze", beforeRequest: { req in
            try req.content.encode(AnalyzeRequest(length: 6))
        }) { res async throws in
            XCTAssertEqual(res.status, .ok, res.body.string)
            let result = try res.content.decode(AnalyzeResult.self)
            XCTAssertLessThanOrEqual(result.suggestedStart, 13.0)
            XCTAssertGreaterThanOrEqual(result.suggestedStart + result.suggestedDuration, 13.6)
        }
        try await app.test(.POST, "api/projects/\(id)/clips/\(Self.newProjectID()).mp4/analyze") { res async in
            XCTAssertEqual(res.status, .notFound)
        }
    }

    // MARK: Helpers

    /// Skips locally when tools are missing; fails in CI (CLIPTHAT_REQUIRE_E2E=1).
    static func requireTools() throws {
        let ok = which("ffmpeg") && which("ffprobe") && which("python3")
        if !ok && ProcessInfo.processInfo.environment["CLIPTHAT_REQUIRE_E2E"] == "1" {
            XCTFail("CLIPTHAT_REQUIRE_E2E=1 but ffmpeg/ffprobe/python3 missing")
        }
        try XCTSkipUnless(ok, "needs ffmpeg, ffprobe and python3")
    }

    static func which(_ tool: String) -> Bool {
        (try? run(["which", tool]))?.isEmpty == false
    }

    @discardableResult
    static func run(_ args: [String]) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = args
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        try process.run()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw XCTSkip("\(args[0]) failed") }
        return String(decoding: data, as: UTF8.self)
    }

    static func makeClip(_ url: URL, color: String, audio: Bool) throws {
        var args = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=\(color):s=320x180:r=15:d=2"]
        if audio { args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", "-shortest"] }
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", url.path]
        try run(args)
    }
}

/// Minimal heterogeneous JSON value for building request bodies in tests.
enum AnyCodableValue: Content, ExpressibleByStringLiteral, ExpressibleByIntegerLiteral, ExpressibleByBooleanLiteral {
    case string(String), int(Int), bool(Bool)

    init(stringLiteral value: String) { self = .string(value) }
    init(integerLiteral value: Int) { self = .int(value) }
    init(booleanLiteral value: Bool) { self = .bool(value) }

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let i = try? c.decode(Int.self) { self = .int(i) }
        else { self = .string(try c.decode(String.self)) }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .int(let i): try c.encode(i)
        case .bool(let b): try c.encode(b)
        }
    }
}
