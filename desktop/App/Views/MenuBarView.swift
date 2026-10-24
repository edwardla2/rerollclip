import AppKit
import ClipThatCore
import SwiftUI

/// Menu bar control so capture stays reachable while a game is full-screen.
struct MenuBarView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Text(replayLine)
        Text(voiceLine)
        if let session = model.selectedSession {
            Text("Saving to “\(session.title)”")
        }
        Divider()
        Button("Clip That (\(model.settings.hotkey.label))") { model.clipThat(trigger: .button) }
            .disabled(model.replayStatus != .buffering)
        Divider()
        Button(model.replayIsActive ? "Turn Off Replay Buffer" : "Turn On Replay Buffer") {
            model.setReplayEnabled(!model.replayIsActive)
        }
        if model.replayStatus == .buffering || model.replayStatus == .paused {
            Button(model.replayStatus == .paused ? "Resume Recording" : "Pause Recording") {
                model.setReplayPaused(model.replayStatus != .paused)
            }
        }
        Button(model.voiceIsOn ? "Stop Listening" : "Listen for “Clip that”") {
            model.setVoiceEnabled(!model.voiceIsOn)
        }
        Divider()
        Button("Open Clip That") {
            openWindow(id: "main")
            NSApp.activate(ignoringOtherApps: true)
        }
        SettingsLink { Text("Settings…") }
        Divider()
        Button("Quit Clip That") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }

    private var replayLine: String {
        switch model.replayStatus {
        case .off: return "Replay buffer: off"
        case .starting: return "Replay buffer: starting…"
        case .buffering: return "● Recording the last \(Int(model.settings.bufferSeconds))s"
        case .paused: return "Replay buffer: paused"
        case .failed: return "Replay buffer: needs attention"
        }
    }

    private var voiceLine: String {
        switch model.voice.status {
        case .listening: return "Listening for “Clip that”"
        case .starting: return "Voice: starting…"
        case .off: return "Voice: off"
        case .unavailable: return "Voice: unavailable"
        }
    }
}
