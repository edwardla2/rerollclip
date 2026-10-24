// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ClipThatContracts",
    platforms: [.macOS(.v15)],
    products: [.library(name: "ClipThatContracts", targets: ["ClipThatContracts"])],
    targets: [
        .target(name: "ClipThatContracts"),
        .testTarget(name: "ClipThatContractsTests", dependencies: ["ClipThatContracts"]),
    ]
)
