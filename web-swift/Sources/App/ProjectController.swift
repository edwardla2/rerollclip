import ClipThatContracts
import Foundation
import Vapor

struct UploadForm: Content {
    var file: File
}

struct UploadResult: Content {
    var file: String
    var bytes: Int
}

struct RenderClip: Content {
    var id: String?
    var file: String
    var startSeconds: Double
    var durationSeconds: Double

    enum CodingKeys: String, CodingKey {
        case id, file
        case startSeconds = "start_seconds"
        case durationSeconds = "duration_seconds"
    }
}

struct RenderRequest: Content {
    var clips: [RenderClip]
    var style: String?
    var layout: String?
    var size: String?
}

struct RenderResult: Content {
    var ok = true
    var url: String
    var bytes: Int
}

/// Upload → render → download for one browser project.
/// A project is a random 128-bit id the browser keeps; it has no account behind it, so
/// this API must not be exposed publicly without authorization (see docs/STATUS.md).
struct ProjectController: RouteCollection {
    let config: ClipThatConfig

    static let allowedExtensions: Set<String> = ["mp4", "mov", "webm", "mkv"]
    static let maxClips = 30
    /// Output sizes offered by the studio: short side → portrait dimensions.
    static let sizes: [String: (Int, Int)] = ["480": (480, 852), "720": (720, 1280), "1080": (1080, 1920)]

    func boot(routes: any RoutesBuilder) throws {
        let project = routes.grouped("api", "projects", ":projectID")
        // Room for multipart framing on top of the file itself.
        let maxBody = ByteCount(value: config.maxUploadBytes + 1024 * 1024)
        project.on(.POST, "clips", body: .collect(maxSize: maxBody), use: upload)
        project.post("render", use: render)
        project.get("output", use: output)
    }

    // MARK: Handlers

    func upload(req: Request) async throws -> UploadResult {
        let dir = try projectDirectory(req)
        let form: UploadForm
        do {
            form = try req.content.decode(UploadForm.self)
        } catch {
            throw Abort(.badRequest, reason: "Attach a video file in the “file” field")
        }
        let ext = (form.file.filename as NSString).pathExtension.lowercased()
        guard Self.allowedExtensions.contains(ext) else {
            throw Abort(.unsupportedMediaType, reason: "Supported video types: MP4, MOV, WebM and MKV")
        }
        let size = form.file.data.readableBytes
        guard size <= config.maxUploadBytes else {
            throw Abort(.payloadTooLarge, reason: "File exceeds the \(config.maxUploadBytes / 1024 / 1024) MB limit")
        }
        guard size > 0 else { throw Abort(.badRequest, reason: "Empty upload") }

        let name = Self.randomHex() + "." + ext
        try await req.fileio.writeFile(form.file.data, at: dir + name)
        pruneExpiredProjects(except: dir, logger: req.logger)
        return UploadResult(file: name, bytes: size)
    }

    func render(req: Request) async throws -> RenderResult {
        let dir = try projectDirectory(req)
        let projectID = req.parameters.get("projectID")!
        let body = try req.content.decode(RenderRequest.self)
        guard (1...Self.maxClips).contains(body.clips.count) else {
            throw Abort(.unprocessableEntity, reason: "Add between 1 and \(Self.maxClips) clips")
        }
        let style = body.style ?? "clean"
        let layout = body.layout ?? "fit_blur"
        let size = body.size ?? "720"
        guard RendererLimits.styles.contains(style) else { throw Abort(.badRequest, reason: "Unsupported preset") }
        guard RendererLimits.layouts.contains(layout) else { throw Abort(.badRequest, reason: "Unsupported layout") }
        guard let (width, height) = Self.sizes[size] else { throw Abort(.badRequest, reason: "Unsupported resolution") }

        var clips: [ClipThatManifest.Clip] = []
        for (index, clip) in body.clips.enumerated() {
            guard Self.isUploadName(clip.file) else {
                throw Abort(.badRequest, reason: "Invalid uploaded clip reference")
            }
            if let id = clip.id, !Self.isClipID(id) {
                throw Abort(.badRequest, reason: "Invalid clip id")
            }
            guard FileManager.default.fileExists(atPath: dir + clip.file) else {
                throw Abort(.notFound, reason: "Uploaded clip no longer exists")
            }
            clips.append(.init(id: clip.id ?? "clip-\(index + 1)", file: clip.file,
                               startSeconds: clip.startSeconds, durationSeconds: clip.durationSeconds))
        }

        let manifest = ClipThatManifest(sessionID: projectID, style: style, layout: layout,
                                        output: .init(width: width, height: height, fps: 30), clips: clips)
        let data: Data
        do {
            data = try manifest.jsonData(pretty: true)
        } catch let error as ClipThatManifest.ValidationError {
            throw Abort(.unprocessableEntity, reason: error.description)
        }
        let manifestPath = dir + "manifest.json"
        let outputPath = dir + "render.mp4"
        try data.write(to: URL(fileURLWithPath: manifestPath), options: .atomic)
        try? FileManager.default.removeItem(atPath: outputPath)

        try await RenderRunner(config: config).render(manifestPath: manifestPath, outputPath: outputPath)

        let bytes = (try? FileManager.default.attributesOfItem(atPath: outputPath)[.size] as? Int) ?? 0
        guard bytes > 0 else { throw Abort(.internalServerError, reason: "Renderer exited without a video") }
        return RenderResult(url: "/api/projects/\(projectID)/output", bytes: bytes)
    }

    func output(req: Request) async throws -> Response {
        let path = try projectDirectory(req) + "render.mp4"
        guard FileManager.default.fileExists(atPath: path) else {
            throw Abort(.notFound, reason: "No rendered video yet")
        }
        let response = try await req.fileio.asyncStreamFile(at: path, mediaType: HTTPMediaType(type: "video", subType: "mp4"))
        response.headers.replaceOrAdd(name: .contentDisposition, value: "attachment; filename=\"clip-that-edit.mp4\"")
        return response
    }

    // MARK: Helpers

    /// Validates the id (32 lowercase hex chars) and returns the project folder, with a trailing slash.
    func projectDirectory(_ req: Request) throws -> String {
        guard let id = req.parameters.get("projectID"), Self.isHex32(id) else {
            throw Abort(.badRequest, reason: "Invalid project ID")
        }
        let dir = config.runtimeDirectory + "/" + id + "/"
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        return dir
    }

    static func isHex32(_ s: String) -> Bool {
        s.count == 32 && s.allSatisfy { ("0"..."9").contains($0) || ("a"..."f").contains($0) }
    }

    /// Server-assigned upload names only: <32 hex>.<allowed ext>. Blocks path traversal.
    static func isUploadName(_ s: String) -> Bool {
        let parts = s.split(separator: ".", omittingEmptySubsequences: false)
        return parts.count == 2 && isHex32(String(parts[0])) && allowedExtensions.contains(String(parts[1]))
    }

    static func isClipID(_ s: String) -> Bool {
        (1...64).contains(s.count) && s.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }
    }

    static func randomHex() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
    }

    /// Deletes project folders nobody has touched within the retention window.
    func pruneExpiredProjects(except keep: String, logger: Logger) {
        let root = config.runtimeDirectory
        let retention = config.retentionSeconds
        Task.detached(priority: .background) {
            let fm = FileManager.default
            guard let names = try? fm.contentsOfDirectory(atPath: root) else { return }
            let cutoff = Date().addingTimeInterval(-retention)
            for name in names where ProjectController.isHex32(name) {
                let path = root + "/" + name + "/"
                guard path != keep,
                      let modified = try? fm.attributesOfItem(atPath: path)[.modificationDate] as? Date,
                      modified < cutoff else { continue }
                try? fm.removeItem(atPath: path)
                logger.info("Deleted expired project \(name)")
            }
        }
    }
}
