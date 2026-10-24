# ClipThatContracts

A dependency-free Swift Package that owns the shared `schema_version: 1` JSON manifest contract between the macOS SwiftUI app and the planned Vapor website.

Run `swift test` in this directory. The tests check encode/decode, validation and compatibility with the original Python/FFmpeg manifest shape.

Neither this shared model nor its tests implement desktop capture, a Vapor server, or video rendering. Existing Python + FFmpeg CLI remains usable as a temporary bridge.
