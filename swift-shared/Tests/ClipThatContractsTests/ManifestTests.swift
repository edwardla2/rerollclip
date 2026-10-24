import Foundation
import Testing
@testable import ClipThatContracts

@Test func roundTripManifest() throws {
    let manifest = ClipThatManifest(sessionID: "session-1", clips: [
        .init(id: "a", file: "clips/a.mp4", startSeconds: 1.5, durationSeconds: 6)
    ])
    let data = try manifest.jsonData(pretty: true)
    let raw = try #require(String(data: data, encoding: .utf8))
    #expect(raw.contains("\"schema_version\""))
    #expect(raw.contains("\"start_seconds\""))
    let decoded = try JSONDecoder().decode(ClipThatManifest.self, from: data)
    #expect(decoded == manifest)
}

@Test func rejectUnsupportedStyle() {
    let manifest = ClipThatManifest(sessionID: "s", style: "unknown", clips: [.init(id: "a", file: "a.mp4", startSeconds: 0, durationSeconds: 4)])
    #expect(throws: ClipThatManifest.ValidationError.self) { try manifest.validate() }
}

@Test func rejectInvalidDuration() {
    let manifest = ClipThatManifest(sessionID: "s", clips: [.init(id: "a", file: "a.mp4", startSeconds: 0, durationSeconds: -1)])
    #expect(throws: ClipThatManifest.ValidationError.self) { try manifest.validate() }
}

@Test func decodeExistingPythonExample() throws {
    // Matches the existing Python manifest format rather than introducing a second schema.
    let json = """
    {"schema_version":1,"session_id":"game-session-001","style":"high_energy","layout":"fit_blur","output":{"width":1080,"height":1920,"fps":30},"clips":[{"id":"moment-001","file":"clips/moment-001.mp4","start_seconds":0,"duration_seconds":6}],"music":null}
    """
    let manifest = try JSONDecoder().decode(ClipThatManifest.self, from: Data(json.utf8))
    try manifest.validate()
    #expect(manifest.clips[0].durationSeconds == 6)
    #expect(manifest.style == "high_energy")
}

@Test func encodesExplicitNullMusicLikeTheExample() throws {
    let manifest = ClipThatManifest(sessionID: "s", clips: [.init(id: "a", file: "clips/a.mp4", startSeconds: 0, durationSeconds: 4)])
    let raw = try #require(String(data: try manifest.jsonData(), encoding: .utf8))
    #expect(raw.contains("\"music\":null"))
    #expect(raw.contains("\"file\":\"clips/a.mp4\""), "slashes stay unescaped")
}

@Test func enforcesRendererLimits() {
    let long = ClipThatManifest(sessionID: "s", clips: [.init(id: "a", file: "a.mp4", startSeconds: 0, durationSeconds: 121)])
    #expect(throws: ClipThatManifest.ValidationError.self) { try long.validate() }
    let odd = ClipThatManifest(sessionID: "s", output: .init(width: 1081, height: 1920, fps: 30),
                               clips: [.init(id: "a", file: "a.mp4", startSeconds: 0, durationSeconds: 4)])
    #expect(throws: ClipThatManifest.ValidationError.self) { try odd.validate() }
    let many = ClipThatManifest(sessionID: "s", clips: (0...100).map { .init(id: "\($0)", file: "a.mp4", startSeconds: 0, durationSeconds: 1) })
    #expect(throws: ClipThatManifest.ValidationError.self) { try many.validate() }
}

@Test func rejectsClipsWithoutIDs() throws {
    // The FastAPI prototype wrote clips without "id". The contract requires one (sync needs stable
    // clip identity), so such manifests fail to decode instead of being silently patched.
    let json = #"{"schema_version":1,"session_id":"x","clips":[{"file":"a.mp4","start_seconds":0,"duration_seconds":2}],"music":null}"#
    #expect(throws: DecodingError.self) { _ = try JSONDecoder().decode(ClipThatManifest.self, from: Data(json.utf8)) }
}
