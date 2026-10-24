import Vapor

struct Health: Content {
    var ok = true
    var mode = "local-demo"
    var renderEngine = "python-ffmpeg"
    var cloudSaving = false

    enum CodingKeys: String, CodingKey {
        case ok, mode
        case renderEngine = "render_engine"
        case cloudSaving = "cloud_saving"
    }
}

func routes(_ app: Application) throws {
    app.get { req async throws -> Response in
        try await page("index.html", req)
    }
    app.get("studio") { req async throws -> Response in
        try await page("studio.html", req)
    }
    app.get("api", "health") { _ async -> Health in
        Health()
    }
    try app.register(collection: BetaInterestController())
    try app.register(collection: ProjectController(config: app.clipThat))
}

private func page(_ name: String, _ req: Request) async throws -> Response {
    try await req.fileio.asyncStreamFile(at: req.application.clipThat.staticDirectory + name, mediaType: .html)
}

/// Turns every error into `{"detail": "..."}` with the right status, matching the
/// browser code's expectations. Unexpected errors are logged and hidden from clients.
struct DetailErrorMiddleware: AsyncMiddleware {
    func respond(to request: Request, chainingTo next: any AsyncResponder) async throws -> Response {
        do {
            return try await next.respond(to: request)
        } catch {
            let status: HTTPResponseStatus
            let reason: String
            if let abort = error as? any AbortError {
                status = abort.status
                reason = abort.reason
            } else {
                status = .internalServerError
                reason = "Something went wrong on the server."
                request.logger.report(error: error)
            }
            let response = Response(status: status)
            try response.content.encode(["detail": reason], as: .json)
            return response
        }
    }
}
