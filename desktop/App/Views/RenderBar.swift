import AppKit
import AVKit
import ClipThatCore
import SwiftUI

/// Bottom bar: edit preset, soundtrack, and the render → preview → export flow.
struct RenderBar: View {
    @EnvironmentObject private var model: AppModel
    let session: Session
    @State private var previewURL: URL?
    @State private var showLog = false

    private var state: RenderState {
        model.renderState.sessionID == session.id ? model.renderState : .idle
    }

    var body: some View {
        HStack(spacing: 14) {
            Picker("Style", selection: Binding(get: { session.settings.style },
                                               set: { model.setStyle($0, for: session.id) })) {
                ForEach(RenderStyle.allCases) { Text($0.label).tag($0) }
            }
            .frame(width: 170)
            .help("Editor preset (the v0 editor accepts these names; distinct looks are coming from the editor side)")

            Picker("Layout", selection: Binding(get: { session.settings.layout },
                                                set: { model.setLayout($0, for: session.id) })) {
                ForEach(RenderLayout.allCases) { Text($0.label).tag($0) }
            }
            .frame(width: 220)

            musicControl

            Spacer()

            status

            renderButton
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(.bar)
        .sheet(item: Binding(get: { previewURL.map(PreviewItem.init) }, set: { previewURL = $0?.url })) { item in
            RenderPreviewSheet(url: item.url, title: session.title)
        }
        .sheet(isPresented: $showLog) {
            if case .failed(_, let message, let log) = state {
                RenderLogSheet(message: message, log: log)
            }
        }
    }

    @ViewBuilder
    private var musicControl: some View {
        if let music = session.settings.musicRelativePath {
            HStack(spacing: 6) {
                Image(systemName: "music.note")
                Text((music as NSString).lastPathComponent)
                    .lineLimit(1)
                    .frame(maxWidth: 120)
                Slider(value: Binding(get: { session.settings.musicVolume },
                                      set: { model.setMusicVolume($0, for: session.id) }), in: 0...1)
                    .frame(width: 70)
                    .help("Music volume")
                Button {
                    model.removeMusic(for: session.id)
                } label: {
                    Image(systemName: "xmark.circle.fill")
                }
                .buttonStyle(.borderless)
            }
        } else {
            Button {
                model.chooseMusic(for: session.id)
            } label: {
                Label("Music", systemImage: "music.note")
            }
            .help("Add a soundtrack you have the rights to use")
        }
    }

    @ViewBuilder
    private var status: some View {
        switch state {
        case .idle:
            if let last = session.renders.first {
                Button("Last render") { previewURL = model.fileURL(last.relativePath, in: session) }
                    .buttonStyle(.link)
            }
        case .rendering(_, let started):
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                TimelineView(.periodic(from: started, by: 1)) { context in
                    Text("Rendering \(session.clips.count) clips · \(Int(context.date.timeIntervalSince(started)))s")
                        .monospacedDigit()
                        .foregroundStyle(.secondary)
                }
            }
        case .finished(_, let url):
            HStack(spacing: 8) {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                Button("Preview") { previewURL = url }
                Button("Export…") { model.export(url, suggestedName: session.title) }
                Button {
                    model.reveal(url)
                } label: {
                    Image(systemName: "folder")
                }
                .help("Show in Finder")
            }
        case .failed(_, let message, _):
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                Text(message)
                    .lineLimit(2)
                    .frame(maxWidth: 320, alignment: .leading)
                    .help(message)
                Button("Details") { showLog = true }
            }
        }
    }

    @ViewBuilder
    private var renderButton: some View {
        if case .rendering = state {
            Button("Cancel") { model.cancelRender() }
        } else {
            Button {
                model.render(session.id)
            } label: {
                Label("Render Montage", systemImage: "wand.and.stars")
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut("r", modifiers: [.command])
            .disabled(session.clips.isEmpty || model.isRendering)
            .help(model.isRendering ? "Another session is rendering" : "Render a 9:16 MP4 with the Clip That editor (⌘R)")
        }
    }
}

private struct PreviewItem: Identifiable {
    let url: URL
    var id: URL { url }
}

struct RenderPreviewSheet: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let url: URL
    let title: String
    @State private var player: AVPlayer?

    var body: some View {
        VStack(spacing: 12) {
            VideoPlayer(player: player)
                .aspectRatio(9 / 16, contentMode: .fit)
                .frame(height: 560)
                .background(Color.black)
            HStack {
                Text(url.lastPathComponent).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("Show in Finder") { model.reveal(url) }
                Button("Export…") { model.export(url, suggestedName: title) }
                Button("Done") { dismiss() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 420)
        .onAppear {
            let p = AVPlayer(url: url)
            player = p
            p.play()
        }
        .onDisappear { player?.pause() }
    }
}

struct RenderLogSheet: View {
    @Environment(\.dismiss) private var dismiss
    let message: String
    let log: String

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Render failed").font(.headline)
            Text(message)
            Text("Your session and clips are unchanged.")
                .foregroundStyle(.secondary)
            ScrollView {
                Text(log.isEmpty ? "No log output." : log)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(height: 260)
            .padding(8)
            .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 6))
            HStack {
                Button("Copy Log") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(message + "\n\n" + log, forType: .string)
                }
                Spacer()
                Button("Close") { dismiss() }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(18)
        .frame(width: 620)
    }
}
