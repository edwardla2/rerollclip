import Fluent
import Foundation
import Vapor

/// Windows beta waitlist: the email, when it was added, and optional tester details
/// (main game, Windows version, graphics card) used to recruit a mix of setups.
final class BetaInterest: Model, @unchecked Sendable {
    static let schema = "beta_interest"
    static let games: Set<String> = ["", "valorant", "cs2", "fortnite", "roblox", "other"]
    static let windowsVersions: Set<String> = ["", "11", "10", "unsure"]

    @ID(custom: "email", generatedBy: .user)
    var id: String?

    @Timestamp(key: "created_at", on: .create)
    var createdAt: Date?

    @OptionalField(key: "game")
    var game: String?

    @OptionalField(key: "windows")
    var windows: String?

    @OptionalField(key: "gpu")
    var gpu: String?

    init() {}

    init(email: String) {
        self.id = email
    }
}

struct CreateBetaInterest: AsyncMigration {
    func prepare(on database: any Database) async throws {
        try await database.schema(BetaInterest.schema)
            .field("email", .string, .identifier(auto: false))
            .field("created_at", .datetime)
            .create()
    }

    func revert(on database: any Database) async throws {
        try await database.schema(BetaInterest.schema).delete()
    }
}

struct AddBetaTesterFields: AsyncMigration {
    // SQLite adds one column per ALTER TABLE, so each column is its own update.
    func prepare(on database: any Database) async throws {
        for key in ["game", "windows", "gpu"] {
            try await database.schema(BetaInterest.schema).field(.string(key), .string).update()
        }
    }

    func revert(on database: any Database) async throws {
        for key in ["game", "windows", "gpu"] {
            try await database.schema(BetaInterest.schema).deleteField(.string(key)).update()
        }
    }
}

struct BetaInterestRequest: Content {
    var email: String
    var consent: Bool?
    var game: String?
    var windows: String?
    var gpu: String?
    /// Honeypot: real people leave it empty.
    var website: String?
}

struct BetaInterestResponse: Content {
    var ok = true
    var mode = "local-interest-only"
    var emailSent = false

    enum CodingKeys: String, CodingKey {
        case ok, mode
        case emailSent = "email_sent"
    }
}

struct BetaInterestController: RouteCollection {
    func boot(routes: any RoutesBuilder) throws {
        routes.post("api", "beta-interest", use: register)
    }

    func register(req: Request) async throws -> BetaInterestResponse {
        let body = try req.content.decode(BetaInterestRequest.self)
        guard (5...254).contains(body.email.count) else {
            throw Abort(.unprocessableEntity, reason: "Enter a valid email address")
        }
        guard body.consent == true else {
            throw Abort(.badRequest, reason: "Please confirm consent to register beta interest")
        }
        let email = body.email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard Self.isEmail(email) else {
            throw Abort(.unprocessableEntity, reason: "Enter a valid email address")
        }
        let game = body.game ?? "", windows = body.windows ?? ""
        guard BetaInterest.games.contains(game), BetaInterest.windowsVersions.contains(windows) else {
            throw Abort(.unprocessableEntity, reason: "Pick a game and Windows version from the list")
        }
        let gpu = Self.cleanGPU(body.gpu ?? "")
        guard gpu.count <= 80, gpu.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) }) else {
            throw Abort(.unprocessableEntity, reason: "Graphics card: letters, numbers and spaces only")
        }
        // Accept bots quietly so the anti-spam rule isn't revealed.
        if let website = body.website, !website.isEmpty { return BetaInterestResponse() }
        // Signing up again keeps the email once and fills in any answers given.
        let entry = try await BetaInterest.find(email, on: req.db) ?? BetaInterest(email: email)
        if !game.isEmpty { entry.game = game }
        if !windows.isEmpty { entry.windows = windows }
        if !gpu.isEmpty { entry.gpu = gpu }
        try await entry.save(on: req.db)
        return BetaInterestResponse()
    }

    /// Collapses runs of whitespace, trims the ends.
    static func cleanGPU(_ s: String) -> String {
        s.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    /// Same rule as the browser: something@something.tld, no spaces.
    static func isEmail(_ s: String) -> Bool {
        let parts = s.split(separator: "@", omittingEmptySubsequences: false)
        guard parts.count == 2, !parts[0].isEmpty, !s.contains(where: \.isWhitespace) else { return false }
        let domain = parts[1].split(separator: ".", omittingEmptySubsequences: false)
        guard domain.count >= 2, domain.dropLast().allSatisfy({ !$0.isEmpty }), let tld = domain.last else { return false }
        return tld.count >= 2
    }
}
