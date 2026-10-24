import Foundation

/// Decides when a running speech transcript contains a new "clip that".
///
/// Speech recognizers re-send the whole transcript as it grows and revises, so the
/// spotter counts phrase occurrences and fires only when the count goes up, with a
/// cooldown so one utterance can't fire twice. Call `reset()` whenever a new
/// recognition task starts (its transcript starts empty).
public struct PhraseSpotter: Sendable {
    public var phrases: [[String]]
    public var cooldown: Double
    private var consumed = 0
    private var lastFire = -Double.infinity

    public init(phrases: [String] = PhraseSpotter.defaultPhrases, cooldown: Double = 2.5) {
        self.phrases = phrases.map { Self.normalize($0).split(separator: " ").map(String.init) }.filter { !$0.isEmpty }
        self.cooldown = cooldown
    }

    /// "clip dat" covers a common recognizer spelling; both are two-word commands that
    /// rarely occur in normal speech.
    public static let defaultPhrases = ["clip that", "clip dat"]

    public mutating func reset() {
        consumed = 0
    }

    /// - Returns: true when this transcript update should trigger a clip.
    public mutating func process(_ transcript: String, at time: Double) -> Bool {
        let words = Self.normalize(transcript).split(separator: " ").map(String.init)
        let count = phrases.reduce(0) { $0 + Self.occurrences(of: $1, in: words) }
        defer { consumed = count }
        guard count > consumed else { return false }
        guard time - lastFire >= cooldown else { return false }
        lastFire = time
        return true
    }

    /// Lowercase, punctuation to spaces, collapse whitespace. Keeps apostrophes.
    public static func normalize(_ text: String) -> String {
        var out = ""
        var lastSpace = true
        for ch in text.lowercased() {
            if ch.isLetter || ch.isNumber || ch == "'" {
                out.append(ch)
                lastSpace = false
            } else if !lastSpace {
                out.append(" ")
                lastSpace = true
            }
        }
        return out.trimmingCharacters(in: .whitespaces)
    }

    static func occurrences(of phrase: [String], in words: [String]) -> Int {
        guard !phrase.isEmpty, words.count >= phrase.count else { return 0 }
        var count = 0
        var i = 0
        while i <= words.count - phrase.count {
            if Array(words[i..<(i + phrase.count)]) == phrase {
                count += 1
                i += phrase.count
            } else {
                i += 1
            }
        }
        return count
    }
}
