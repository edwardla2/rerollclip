import Fluent
import FluentSQLiteDriver
import Foundation
import Vapor

/// Runtime settings. Everything has an environment variable so the same binary runs
/// locally and on a host.
struct ClipThatConfig: Sendable {
    /// Folder with index.html, studio.html and assets/ (trailing slash).
    var staticDirectory: String
    /// Where uploads, manifests and renders live (one subfolder per project).
    var runtimeDirectory: String
    /// Folder that contains the `clipthat_editor` package.
    var editorRoot: String
    /// Command that starts Python, e.g. ["/usr/bin/env", "python3"].
    var pythonCommand: [String]
    var maxUploadBytes: Int
    var renderTimeoutSeconds: Double
    /// Project folders untouched for this long are deleted.
    var retentionSeconds: Double
    /// SQLite file for beta-interest emails; nil keeps it in memory (tests).
    var databasePath: String?

    static func fromEnvironment() -> ClipThatConfig {
        let env = ProcessInfo.processInfo.environment
        let repoRoot = env["CLIPTHAT_REPO_ROOT"].map(withSlash)
            ?? withSlash(URL(fileURLWithPath: DirectoryConfiguration.detect().workingDirectory)
                .appendingPathComponent("..").standardizedFileURL.path)
        let runtime = env["CLIPTHAT_WEB_DATA"] ?? repoRoot + ".web_runtime"
        return ClipThatConfig(
            staticDirectory: withSlash(env["CLIPTHAT_STATIC_DIR"] ?? repoRoot + "web/static"),
            runtimeDirectory: runtime,
            editorRoot: env["CLIPTHAT_EDITOR_ROOT"] ?? repoRoot,
            pythonCommand: (env["CLIPTHAT_PYTHON"]).map { [$0] } ?? ["/usr/bin/env", "python3"],
            maxUploadBytes: (env["CLIPTHAT_MAX_UPLOAD_MB"].flatMap(Int.init) ?? 250) * 1024 * 1024,
            renderTimeoutSeconds: env["CLIPTHAT_RENDER_TIMEOUT"].flatMap(Double.init) ?? 600,
            retentionSeconds: (env["CLIPTHAT_RETENTION_HOURS"].flatMap(Double.init) ?? 24) * 3600,
            databasePath: env["CLIPTHAT_DB"] ?? runtime + "/clipthat.sqlite3"
        )
    }

    private static func withSlash(_ path: String) -> String {
        path.hasSuffix("/") ? path : path + "/"
    }
}

private struct ClipThatConfigKey: StorageKey {
    typealias Value = ClipThatConfig
}

extension Application {
    var clipThat: ClipThatConfig {
        get {
            guard let value = storage[ClipThatConfigKey.self] else { fatalError("configure(_:) not called") }
            return value
        }
        set { storage[ClipThatConfigKey.self] = newValue }
    }
}

public func configure(_ app: Application) async throws {
    try await configure(app, config: .fromEnvironment())
}

func configure(_ app: Application, config: ClipThatConfig) async throws {
    app.clipThat = config
    try FileManager.default.createDirectory(atPath: config.runtimeDirectory, withIntermediateDirectories: true)

    // Errors come back as {"detail": "..."} so the browser code reads one shape.
    app.middleware = Middlewares()
    app.middleware.use(DetailErrorMiddleware())
    app.middleware.use(FileMiddleware(publicDirectory: config.staticDirectory))

    app.routes.defaultMaxBodySize = "1mb"
    app.http.server.configuration.hostname = Environment.get("HOST") ?? "127.0.0.1"
    app.http.server.configuration.port = Environment.get("PORT").flatMap(Int.init) ?? 8765

    if let path = config.databasePath {
        app.databases.use(.sqlite(.file(path)), as: .sqlite)
    } else {
        app.databases.use(.sqlite(.memory), as: .sqlite)
    }
    app.migrations.add(CreateBetaInterest())
    try await app.autoMigrate()

    try routes(app)
}
