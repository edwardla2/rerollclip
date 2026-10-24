import ClipThatCore
import SwiftUI

/// Always-visible capture controls with explicit on/off state for recording and listening.
struct CaptureBar: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            controls
            if case .failed(let message) = model.replayStatus {
                Divider()
                PermissionHint(message: message)
            }
        }
    }

    private var controls: some View {
        HStack(spacing: 18) {
            replayControl
            voiceControl
            Spacer()
            if model.savingClips > 0 {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.small)
                    Text("Saving clip…").foregroundStyle(.secondary)
                }
            }
            Text("Shortcut \(model.settings.hotkey.label)")
                .font(.caption)
                .foregroundStyle(model.hotkeyRegistered ? Color.secondary : Color.orange)
                .help(model.hotkeyRegistered ? "Press anywhere, even in a full-screen game" : "Shortcut unavailable. Choose another in Settings.")
            Button {
                model.clipThat(trigger: .button)
            } label: {
                Label("Clip That", systemImage: "scissors")
            }
            .disabled(model.replayStatus != .buffering)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
    }

    private var replayControl: some View {
        HStack(spacing: 8) {
            Toggle(isOn: Binding(get: { model.replayIsActive }, set: { model.setReplayEnabled($0) })) {
                Text("Replay buffer")
            }
            .toggleStyle(.switch)
            .controlSize(.small)
            StatusPill(text: replayText, color: replayColor)
            if model.replayStatus == .buffering || model.replayStatus == .paused {
                Button(model.replayStatus == .paused ? "Resume" : "Pause") {
                    model.setReplayPaused(model.replayStatus != .paused)
                }
                .controlSize(.small)
                .help("Pause while something private is on screen")
            }
        }
    }

    private var voiceControl: some View {
        HStack(spacing: 8) {
            Toggle(isOn: Binding(get: { model.voiceIsOn }, set: { model.setVoiceEnabled($0) })) {
                Text("“Clip that”")
            }
            .toggleStyle(.switch)
            .controlSize(.small)
            StatusPill(text: voiceText, color: voiceColor)
        }
    }

    private var replayText: String {
        switch model.replayStatus {
        case .off: return "Off"
        case .starting: return "Starting…"
        case .buffering: return "Recording · last \(Int(model.bufferedSeconds))s"
        case .paused: return "Paused"
        case .failed: return "Needs attention"
        }
    }

    private var replayColor: Color {
        switch model.replayStatus {
        case .buffering: return .red
        case .paused, .starting: return .orange
        case .failed: return .orange
        case .off: return .secondary
        }
    }

    private var voiceText: String {
        switch model.voice.status {
        case .off: return "Off"
        case .starting: return "Starting…"
        case .listening: return "Listening"
        case .unavailable: return "Unavailable"
        }
    }

    private var voiceColor: Color {
        switch model.voice.status {
        case .listening: return .green
        case .starting: return .orange
        case .unavailable: return .orange
        case .off: return .secondary
        }
    }
}

struct StatusPill: View {
    let text: String
    let color: Color

    var body: some View {
        HStack(spacing: 5) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(text).font(.caption.monospacedDigit())
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(color.opacity(0.12), in: Capsule())
    }
}

/// Non-destructive recovery when a permission is missing or capture stopped.
struct PermissionHint: View {
    @EnvironmentObject private var model: AppModel
    let message: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "lock.shield").foregroundStyle(.orange)
            Text(message).font(.caption).lineLimit(3)
            Button("Open System Settings") { Permissions.open(.screenRecording) }
                .controlSize(.small)
            Button("Try Again") { model.setReplayEnabled(true) }
                .controlSize(.small)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(Color.orange.opacity(0.08))
    }
}
