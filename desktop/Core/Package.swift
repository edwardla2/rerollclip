// swift-tools-version: 6.0
// ClipThatCore: platform-independent logic for the Clip That desktop app.
// Foundation only (no AppKit/AVFoundation), so it builds and tests with `swift test`
// on macOS and Linux. Talks to the editor exclusively through its CLI + manifest.
import PackageDescription

let package = Package(
    name: "ClipThatCore",
    platforms: [.macOS(.v15)],
    products: [
        .library(name: "ClipThatCore", targets: ["ClipThatCore"]),
    ],
    dependencies: [
        // The one schema definition, shared with the website.
        .package(path: "../../swift-shared"),
    ],
    targets: [
        .target(name: "ClipThatCore",
                dependencies: [.product(name: "ClipThatContracts", package: "swift-shared")],
                swiftSettings: [.swiftLanguageMode(.v5)]),
        .testTarget(name: "ClipThatCoreTests", dependencies: ["ClipThatCore"], swiftSettings: [.swiftLanguageMode(.v5)]),
    ]
)
