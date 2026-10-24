// swift-tools-version: 5.9
// ClipThatCore: platform-independent logic for the Clip That desktop app.
// Foundation only (no AppKit/AVFoundation), so it builds and tests with `swift test`
// on macOS and Linux. Talks to the editor exclusively through its CLI + manifest.
import PackageDescription

let package = Package(
    name: "ClipThatCore",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "ClipThatCore", targets: ["ClipThatCore"]),
    ],
    targets: [
        .target(name: "ClipThatCore"),
        .testTarget(name: "ClipThatCoreTests", dependencies: ["ClipThatCore"]),
    ]
)
