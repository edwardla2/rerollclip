import Fluent
import Foundation
import Vapor

/// Mac beta interest list. Stores only the email and when it was added.
final class BetaInterest: Model, @unchecked Sendable {
    static let schema = "beta_interest"

    @ID(custom: "email", generatedBy: .user)
    var id: String?

    @Timestamp(key: "created_at", on: .create)
    var createdAt: Date?

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

struct BetaInterestRequest: Content {
    var email: String
    var consent: Bool?
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
        // Accept bots quietly so the anti-spam rule isn't revealed.
        if let website = body.website, !website.isEmpty { return BetaInterestResponse() }
        if try await BetaInterest.find(email, on: req.db) == nil {
            try await BetaInterest(email: email).create(on: req.db)
        }
        return BetaInterestResponse()
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
