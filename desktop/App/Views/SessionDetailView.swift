import AVKit
import ClipThatCore
import SwiftUI

struct SessionDetailView: View {
    @EnvironmentObject private var model: AppModel
    let session: Session
    @State private var confirmRemove: Clip?

    var body: some View {
        VStack(spacing: 0) {
            if session.clips.isEmpty {
                EmptySessionView()
            } else {
                HSplitView {
                    clipList
                        .frame(minWidth: 300, idealWidth: 360, maxWidth: 480)
                    ClipInspectorView(session: session)
                        .frame(minWidth: 420, maxWidth: .infinity)
                }
            }
            Divider()
            RenderBar(session: session)
        }
        .dropDestination(for: URL.self) { urls, _ in
            model.importFiles(urls)
            return true
        }
        .navigationTitle(session.title)
        .navigationSubtitle(session.clips.isEmpty ? "" : "\(session.clips.count) clips · \(DurationFormat.clock(session.totalSelectedSeconds)) selected")
        .toolbar {
            ToolbarItem {
                Button {
                    model.presentImportPanel()
                } label: {
                    Label("Import Clips", systemImage: "square.and.arrow.down")
                }
                .help("Import clips exported by another recorder (⌘I)")
            }
            ToolbarItem {
                if model.importsInFlight > 0 {
                    ProgressView().controlSize(.small)
                        .help("Importing \(model.importsInFlight) file(s)…")
                }
            }
        }
        .confirmationDialog("Remove “\(confirmRemove?.displayName ?? "")”?",
                            isPresented: Binding(get: { confirmRemove != nil }, set: { if !$0 { confirmRemove = nil } })) {
            Button("Move Clip to Trash", role: .destructive) {
                if let confirmRemove { model.removeClip(confirmRemove.id, from: session.id) }
                confirmRemove = nil
            }
        } message: {
            Text("The clip file goes to the Trash, so you can still restore it.")
        }
    }

    private var clipList: some View {
        List(selection: $model.selectedClipID) {
            ForEach(Array(session.clips.enumerated()), id: \.element.id) { index, clip in
                ClipRowView(clip: clip, index: index + 1, url: model.clipURL(clip, in: session))
                    .tag(clip.id)
                    .contextMenu {
                        Button("Move Up") { model.moveClip(clip.id, in: session.id, by: -1) }
                            .disabled(index == 0)
                        Button("Move Down") { model.moveClip(clip.id, in: session.id, by: 1) }
                            .disabled(index == session.clips.count - 1)
                        Divider()
                        Button("Show in Finder") { model.reveal(model.clipURL(clip, in: session)) }
                        Divider()
                        Button("Remove…", role: .destructive) { confirmRemove = clip }
                    }
            }
            .onMove { offsets, destination in
                model.moveClips(in: session.id, from: offsets, to: destination)
            }
        }
        .onDeleteCommand {
            if let id = model.selectedClipID { confirmRemove = session.clips.first { $0.id == id } }
        }
    }
}

struct EmptySessionView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "sparkles.rectangle.stack")
                .font(.system(size: 40, weight: .light))
                .foregroundStyle(.secondary)
            Text("No clips yet")
                .font(.title3.weight(.semibold))
            Text("Turn on the replay buffer and say “Clip that” (or press \(model.settings.hotkey.label)),\nor import clips from another recorder. You can also drop files here.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            HStack {
                Button("Import Clips…") { model.presentImportPanel() }
                if !model.replayIsActive {
                    Button("Turn On Replay Buffer") { model.setReplayEnabled(true) }
                        .buttonStyle(.borderedProminent)
                }
            }
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct ClipRowView: View {
    let clip: Clip
    let index: Int
    let url: URL

    var body: some View {
        HStack(spacing: 10) {
            Text("\(index)")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 18, alignment: .trailing)
            ClipThumbnail(url: url)
                .frame(width: 96, height: 54)
                .clipShape(RoundedRectangle(cornerRadius: 5))
            VStack(alignment: .leading, spacing: 3) {
                Text(clip.sourceLabel)
                    .font(.callout.weight(.medium))
                    .lineLimit(1)
                Text(clip.capturedAt.formatted(date: .abbreviated, time: .standard))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack(spacing: 6) {
                    Text(trimLabel)
                    if !clip.hasAudio {
                        Image(systemName: "speaker.slash").help("No audio track")
                    }
                    if clip.hasMicTrack {
                        Image(systemName: "mic").help("Includes a separate microphone track")
                    }
                }
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 3)
    }

    private var trimLabel: String {
        let full = abs(clip.selectionDuration - clip.mediaDuration) < 0.05 && clip.selectionStart < 0.05
        return full ? DurationFormat.clock(clip.mediaDuration)
            : "\(DurationFormat.short(clip.selectionDuration)) of \(DurationFormat.clock(clip.mediaDuration))"
    }
}
