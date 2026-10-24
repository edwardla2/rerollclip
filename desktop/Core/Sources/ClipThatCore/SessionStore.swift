import Foundation

/// On-disk session library. Layout:
///
///     <root>/Sessions/<session-id>/
///         session.json      desktop metadata (clip order, trims, provenance)
///         manifest.json     written right before each render (editor contract)
///         clips/            clip media; manifest paths are relative to the session folder
///         music/            optional soundtrack copied in
///         renders/          finished montages
///
/// Default root is ~/Movies/Clip That so users can find their footage in Finder.
public final class SessionStore: @unchecked Sendable {
    public let root: URL
    private let fm = FileManager.default

    public init(root: URL) {
        self.root = root
    }

    public static func defaultRoot() -> URL {
        let movies = FileManager.default.urls(for: .moviesDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Movies", isDirectory: true)
        return movies.appendingPathComponent("Clip That", isDirectory: true)
    }

    public var sessionsDirectory: URL {
        root.appendingPathComponent("Sessions", isDirectory: true)
    }

    // MARK: Paths

    public func directory(for sessionID: String) -> URL {
        sessionsDirectory.appendingPathComponent(sessionID, isDirectory: true)
    }

    public func url(_ relativePath: String, in session: Session) -> URL {
        directory(for: session.id).appendingPathComponent(relativePath)
    }

    public func url(for clip: Clip, in session: Session) -> URL {
        url(clip.relativePath, in: session)
    }

    public func manifestURL(for session: Session) -> URL {
        directory(for: session.id).appendingPathComponent("manifest.json")
    }

    public func fileExists(_ relativePath: String, in session: Session) -> Bool {
        fm.fileExists(atPath: url(relativePath, in: session).path)
    }

    // MARK: Load / save

    public func loadAll() -> [Session] {
        guard let entries = try? fm.contentsOfDirectory(at: sessionsDirectory, includingPropertiesForKeys: nil,
                                                         options: [.skipsHiddenFiles]) else { return [] }
        return entries.compactMap { dir -> Session? in
            let file = dir.appendingPathComponent("session.json")
            guard let data = try? Data(contentsOf: file) else { return nil }
            return try? Self.decoder.decode(Session.self, from: data)
        }
        .sorted { $0.createdAt > $1.createdAt }
    }

    @discardableResult
    public func create(title: String? = nil, now: Date = Date()) throws -> Session {
        let id = Self.makeSessionID(now: now)
        let session = Session(id: id, title: title ?? Self.defaultTitle(now: now), createdAt: now)
        try fm.createDirectory(at: directory(for: id).appendingPathComponent("clips", isDirectory: true),
                               withIntermediateDirectories: true)
        try save(session)
        return session
    }

    public func save(_ session: Session) throws {
        let dir = directory(for: session.id)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        let data = try Self.encoder.encode(session)
        try data.write(to: dir.appendingPathComponent("session.json"), options: .atomic)
    }

    /// Moves the whole session folder to the Trash (recoverable) on macOS.
    public func delete(_ session: Session) throws {
        try discard(directory(for: session.id))
    }

    /// Removes a clip's media file (to the Trash on macOS). Does not edit session.json.
    public func discardFile(_ relativePath: String, in session: Session) throws {
        let file = url(relativePath, in: session)
        guard fm.fileExists(atPath: file.path) else { return }
        try discard(file)
    }

    private func discard(_ url: URL) throws {
        #if os(macOS)
        try fm.trashItem(at: url, resultingItemURL: nil)
        #else
        try fm.removeItem(at: url)
        #endif
    }

    // MARK: New files

    /// A non-colliding destination inside a session subfolder ("clips", "music", "renders").
    public func uniqueDestination(in session: Session, folder: String, baseName: String,
                                  ext: String) throws -> (url: URL, relativePath: String) {
        let dir = directory(for: session.id).appendingPathComponent(folder, isDirectory: true)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        let cleanBase = Self.sanitize(baseName)
        let cleanExt = ext.lowercased()
        var name = "\(cleanBase).\(cleanExt)"
        var n = 2
        while fm.fileExists(atPath: dir.appendingPathComponent(name).path) {
            name = "\(cleanBase)-\(n).\(cleanExt)"
            n += 1
        }
        return (dir.appendingPathComponent(name), "\(folder)/\(name)")
    }

    // MARK: Helpers

    public static func makeSessionID(now: Date) -> String {
        "s-" + stamp(now) + "-" + UUID().uuidString.prefix(4).lowercased()
    }

    public static func defaultTitle(now: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "MMM d, h:mm a"
        return "Session · " + f.string(from: now)
    }

    /// 2026-10-24 18:14:03 -> "20261024-181403" (local time, for readable file names)
    public static func stamp(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f.string(from: date)
    }

    /// File-name-safe slug: letters, digits, dash, underscore; max 60 chars.
    public static func sanitize(_ name: String) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_"))
        var out = ""
        var lastDash = false
        for scalar in name.unicodeScalars {
            if allowed.contains(scalar) && scalar.isASCII {
                out.unicodeScalars.append(scalar)
                lastDash = false
            } else if !lastDash {
                out.append("-")
                lastDash = true
            }
        }
        let trimmed = out.trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        let limited = String(trimmed.prefix(60))
        return limited.isEmpty ? "clip" : limited
    }

    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()
}
