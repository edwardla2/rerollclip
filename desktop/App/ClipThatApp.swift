import AppKit
import ClipThatCore
import SwiftUI

@main
struct ClipThatApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @ObservedObject private var model = AppModel.shared

    var body: some Scene {
        Window("Clip That", id: "main") {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 980, minHeight: 620)
        }
        .defaultSize(width: 1180, height: 760)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Session") { model.newSession() }
                    .keyboardShortcut("n")
                Button("Import Clips…") { model.presentImportPanel() }
                    .keyboardShortcut("i")
            }
            CommandMenu("Capture") {
                Button("Clip That") { model.clipThat(trigger: .button) }
                    .keyboardShortcut("k")
                Divider()
                Button(model.replayIsActive ? "Turn Off Replay Buffer" : "Turn On Replay Buffer") {
                    model.setReplayEnabled(!model.replayIsActive)
                }
                Button(model.voiceIsOn ? "Stop Listening for “Clip that”" : "Listen for “Clip that”") {
                    model.setVoiceEnabled(!model.voiceIsOn)
                }
            }
        }

        MenuBarExtra {
            MenuBarView()
                .environmentObject(model)
        } label: {
            Image(systemName: model.replayStatus == .buffering ? "record.circle.fill" : "scissors")
        }

        Settings {
            SettingsView()
                .environmentObject(model)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    /// Keep running in the menu bar when the window closes, so the hotkey and voice
    /// trigger keep working while gaming.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    /// Stop capture and wipe the replay buffer before quitting.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        Task { @MainActor in
            await AppModel.shared.shutdown()
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}
