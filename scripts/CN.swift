import Foundation

/// Display boundary only: never use this helper for persistence, keys or user-entered text.
enum CN {
    static var enabled: Bool {
        UserDefaults.standard.object(forKey: "CompositorChineseEnabled") == nil
            || UserDefaults.standard.bool(forKey: "CompositorChineseEnabled")
    }
    private static let dictionary: [String: String] = {
        guard let url = Bundle.main.url(forResource: "zh-CN", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let values = try? JSONDecoder().decode([String: String].self, from: data) else { return [:] }
        return values
    }()
    private struct Rule {
        let regex: NSRegularExpression
        let value: String
        let indices: [String]
    }
    private static let rules: [Rule] = dictionary.keys.sorted {
        if $0.count == $1.count { return $0 < $1 }
        return $0.count > $1.count
    }.compactMap { key in
        let marker = try! NSRegularExpression(pattern: #"\{[0-9]+\}"#)
        let ns = key as NSString
        let matches = marker.matches(in: key, range: NSRange(location: 0, length: ns.length))
        guard !matches.isEmpty, key.replacingOccurrences(of: #"\{[0-9]+\}"#, with: "", options: .regularExpression).count >= 3 else { return nil }
        var pattern = "^"; var last = 0; var indices: [String] = []
        for match in matches {
            pattern += NSRegularExpression.escapedPattern(for: ns.substring(with: NSRange(location: last, length: match.range.location - last)))
            pattern += "(.*?)"
            indices.append(ns.substring(with: match.range))
            last = NSMaxRange(match.range)
        }
        pattern += NSRegularExpression.escapedPattern(for: ns.substring(from: last)) + "$"
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.dotMatchesLineSeparators]), let value = dictionary[key] else { return nil }
        return Rule(regex: regex, value: value, indices: indices)
    }
    static func text(_ source: String) -> String {
        guard enabled else { return source }
        if let value = dictionary[source] { return value }
        for suffix in ["…", "..."] where source.hasSuffix(suffix) {
            if let value = dictionary[String(source.dropLast(suffix.count))] { return value + suffix }
        }
        let ns = source as NSString
        for rule in rules {
            guard let match = rule.regex.firstMatch(in: source, range: NSRange(location: 0, length: ns.length)) else { continue }
            // Substitute in one pass so placeholders inside user text stay untouched.
            let marker = try! NSRegularExpression(pattern: #"\{[0-9]+\}"#)
            let result = NSMutableString(string: rule.value)
            for token in marker.matches(in: rule.value, range: NSRange(location: 0, length: (rule.value as NSString).length)).reversed() {
                let name = (rule.value as NSString).substring(with: token.range)
                if let index = rule.indices.firstIndex(of: name) {
                    result.replaceCharacters(in: token.range, with: ns.substring(with: match.range(at: index + 1)))
                }
            }
            return result as String
        }
        return source
    }
}
