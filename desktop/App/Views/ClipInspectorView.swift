import AppKit
import AVKit
import ClipThatCore
import SwiftUI

/// Preview player + in/out selection for the selected clip.
struct ClipInspectorView: View {
    @EnvironmentObject private var model: AppModel
    let session: Session

    @State private var player = AVPlayer()
    @State private var loadedURL: URL?
    @State private var startText = ""
    @State private var lengthText = ""
    @State private var boundaryObserver: Any?

    private var clip: Clip? {
        session.clips.first { $0.id == model.selectedClipID }
    }

    var body: some View {
        if let clip {
            VStack(alignment: .leading, spacing: 14) {
                VideoPlayer(player: player)
                    .aspectRatio(16 / 9, contentMode: .fit)
                    .background(Color.black)
                    .clipShape(RoundedRectangle(cornerRadius: 8))

                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(clip.sourceLabel).font(.headline)
                        Text(clip.displayName).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer()
                    Button {
                        playSelection(clip)
                    } label: {
                        Label("Play Selection", systemImage: "play.fill")
                    }
                }

                GroupBox("Selection") {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack(spacing: 16) {
                            LabeledContent("Start") {
                                TextField("0", text: $startText)
                                    .frame(width: 70)
                                    .multilineTextAlignment(.trailing)
                                    .onSubmit { commit(clip) }
                            }
                            LabeledContent("Length") {
                                TextField("0", text: $lengthText)
                                    .frame(width: 70)
                                    .multilineTextAlignment(.trailing)
                                    .onSubmit { commit(clip) }
                            }
                            Text("seconds of \(DurationFormat.short(clip.mediaDuration))")
                                .foregroundStyle(.secondary)
                            Spacer()
                        }
                        HStack {
                            Button("Set Start to Playhead") {
                                let now = player.currentTime().seconds
                                let end = clip.selectionStart + clip.selectionDuration
                                model.setSelection(clip.id, in: session.id, start: now, duration: max(0.1, end - now))
                            }
                            Button("Set End to Playhead") {
                                let now = player.currentTime().seconds
                                model.setSelection(clip.id, in: session.id, start: clip.selectionStart,
                                                   duration: max(0.1, now - clip.selectionStart))
                            }
                            Spacer()
                            Button("Use Whole Clip") { model.resetSelection(clip.id, in: session.id) }
                        }
                        HStack(spacing: 8) {
                            Button {
                                model.suggestTrim(clip.id, in: session.id)
                            } label: {
                                Label(model.analyzingClipIDs.contains(clip.id) ? "Analyzing…" : "Suggest Trim",
                                      systemImage: "wand.and.rays")
                            }
                            .disabled(model.analyzingClipIDs.contains(clip.id))
                            Picker("Length", selection: $model.autoTrimLength) {
                                Text("5 s").tag(5.0)
                                Text("8 s").tag(8.0)
                                Text("12 s").tag(12.0)
                            }
                            .labelsHidden()
                            .frame(width: 70)
                            Text(clip.triggerOffset != nil
                                 ? "Looks at the moment just before you said “Clip that.”"
                                 : "Finds the loudest, busiest moment.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        if let offset = clip.triggerOffset {
                            Text("Trigger heard at \(DurationFormat.short(offset)) into this clip.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        if clip.mediaDuration > RendererLimits.maxClipSeconds {
                            Text("The editor uses up to \(Int(RendererLimits.maxClipSeconds)) s per clip, so this long recording starts with its last 30 s selected.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(6)
                }
                Spacer(minLength: 0)
            }
            .padding(16)
            .onAppear { load(clip) }
            .onChange(of: clip) { _, newClip in load(newClip) }
            .onDisappear {
                player.pause()
                removeBoundary()
            }
        } else {
            Text("Select a clip to preview it.")
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func load(_ clip: Clip) {
        startText = String(format: "%.2f", clip.selectionStart)
        lengthText = String(format: "%.2f", clip.selectionDuration)
        let url = model.clipURL(clip, in: session)
        if loadedURL != url {
            removeBoundary()
            player.replaceCurrentItem(with: AVPlayerItem(url: url))
            loadedURL = url
            player.seek(to: CMTime(seconds: clip.selectionStart, preferredTimescale: 600))
        }
    }

    private func commit(_ clip: Clip) {
        let start = Double(startText.replacingOccurrences(of: ",", with: ".")) ?? clip.selectionStart
        let length = Double(lengthText.replacingOccurrences(of: ",", with: ".")) ?? clip.selectionDuration
        model.setSelection(clip.id, in: session.id, start: start, duration: length)
    }

    private func playSelection(_ clip: Clip) {
        removeBoundary()
        let end = CMTime(seconds: clip.selectionStart + clip.selectionDuration, preferredTimescale: 600)
        let avPlayer = player
        boundaryObserver = avPlayer.addBoundaryTimeObserver(forTimes: [NSValue(time: end)], queue: .main) {
            avPlayer.pause()
        }
        avPlayer.seek(to: CMTime(seconds: clip.selectionStart, preferredTimescale: 600),
                      toleranceBefore: .zero, toleranceAfter: .zero) { _ in
            avPlayer.play()
        }
    }

    private func removeBoundary() {
        if let boundaryObserver { player.removeTimeObserver(boundaryObserver) }
        boundaryObserver = nil
    }
}

/// Async thumbnail from the middle of a clip.
struct ClipThumbnail: View {
    let url: URL
    @State private var image: NSImage?

    var body: some View {
        ZStack {
            Rectangle().fill(Color.black.opacity(0.85))
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
            } else {
                Image(systemName: "film").foregroundStyle(.secondary)
            }
        }
        .task(id: url) {
            image = await ThumbnailCache.shared.thumbnail(for: url)
        }
    }
}

actor ThumbnailCache {
    static let shared = ThumbnailCache()
    private var cache: [URL: NSImage] = [:]

    func thumbnail(for url: URL) async -> NSImage? {
        if let cached = cache[url] { return cached }
        let asset = AVURLAsset(url: url)
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: 320, height: 180)
        let duration = (try? await asset.load(.duration))?.seconds ?? 0
        let time = CMTime(seconds: max(0, duration * 0.5), preferredTimescale: 600)
        guard let result = try? await generator.image(at: time) else { return nil }
        let image = NSImage(cgImage: result.image, size: NSSize(width: result.image.width, height: result.image.height))
        cache[url] = image
        return image
    }
}
