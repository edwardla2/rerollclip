import AppKit
import ClipThatCore
import SwiftUI

struct SettingsView: View {
    var body: some View {
        TabView {
            CaptureSettings().tabItem { Label("Capture", systemImage: "record.circle") }
            VoiceSettings().tabItem { Label("Voice", systemImage: "waveform") }
            ImportSettings().tabItem { Label("Imports", systemImage: "tray.and.arrow.down") }
            PermissionSettings().tabItem { Label("Privacy", systemImage: "hand.raised") }
            EngineSettings().tabItem { Label("Engine", systemImage: "gearshape.2") }
        }
        .frame(width: 600, height: 470)
    }
}

// MARK: - Capture

private struct CaptureSettings: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        Form {
            Section {
                Picker("Save the last", selection: $model.settings.bufferSeconds) {
                    Text("15 seconds").tag(15.0)
                    Text("30 seconds").tag(30.0)
                    Text("45 seconds").tag(45.0)
                    Text("60 seconds").tag(60.0)
                }
                Picker("Keep recording after the trigger", selection: $model.settings.postRollSeconds) {
                    Text("None").tag(0.0)
                    Text("1.5 seconds").tag(1.5)
                    Text("3 seconds").tag(3.0)
                }
                Picker("Frame rate", selection: $model.settings.captureFPS) {
                    Text("30 fps").tag(30)
                    Text("60 fps").tag(60)
                }
                Picker("Resolution", selection: $model.settings.captureMaxHeight) {
                    Text("720p").tag(720)
                    Text("1080p").tag(1080)
                    Text("1440p").tag(1440)
                }
                Picker("Shortcut for “Clip that”", selection: $model.settings.hotkey) {
                    ForEach(HotkeyChoice.allCases) { Text($0.label).tag($0) }
                }
                Toggle("Play a sound when a clip is saved", isOn: $model.settings.playSounds)
            } footer: {
                Text("Only the last \(Int(model.settings.bufferSeconds)) seconds are kept, in a private cache that's deleted when the buffer turns off. Nothing is uploaded.")
                    .foregroundStyle(.secondary)
            }

            Section("Microphone") {
                Toggle("Record my microphone into clips", isOn: $model.settings.includeMicrophone)
                Toggle("Mix my mic into the clip's main audio", isOn: $model.settings.mixMicIntoClip)
                    .disabled(!model.settings.includeMicrophone)
                Text("Your mic is also kept as a separate track so it can be removed or lowered later.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section {
                ForEach(model.settings.excludedBundleIDs, id: \.self) { bundleID in
                    HStack {
                        Text(Self.appName(for: bundleID))
                        Spacer()
                        Button("Remove") { model.settings.excludedBundleIDs.removeAll { $0 == bundleID } }
                            .buttonStyle(.borderless)
                    }
                }
                Menu("Exclude an App…") {
                    ForEach(Self.runningApps(excluding: model.settings.excludedBundleIDs), id: \.bundleID) { app in
                        Button(app.name) { model.settings.excludedBundleIDs.append(app.bundleID) }
                    }
                }
            } header: {
                Text("Never record these apps")
            } footer: {
                Text("Windows of excluded apps (a banking site's browser profile, a password manager) are left out of the capture. Clip That's own windows are always excluded. You can also pause recording from the capture bar or menu bar.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
    }

    struct RunningApp {
        var bundleID: String
        var name: String
    }

    static func runningApps(excluding: [String]) -> [RunningApp] {
        NSWorkspace.shared.runningApplications
            .filter { $0.activationPolicy == .regular }
            .compactMap { app -> RunningApp? in
                guard let id = app.bundleIdentifier, id != Bundle.main.bundleIdentifier, !excluding.contains(id) else { return nil }
                return RunningApp(bundleID: id, name: app.localizedName ?? id)
            }
            .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }

    static func appName(for bundleID: String) -> String {
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) {
            return FileManager.default.displayName(atPath: url.path).replacingOccurrences(of: ".app", with: "")
        }
        return bundleID
    }
}

// MARK: - Voice

private struct VoiceSettings: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        Form {
            Section {
                Toggle("Listen for “Clip that”", isOn: Binding(get: { model.voiceIsOn }, set: { model.setVoiceEnabled($0) }))
                LabeledContent("Status", value: statusText)
                if model.voiceIsOn {
                    LabeledContent("Last heard") {
                        Text(model.voice.lastHeard.isEmpty ? "…" : model.voice.lastHeard)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
            } footer: {
                Text("Speech is recognized on this Mac only. Nothing is recorded or sent anywhere. Say “Clip that” clearly; headphones help so game audio from your speakers doesn't reach the mic.")
                    .foregroundStyle(.secondary)
            }
            if case .unavailable(let reason) = model.voice.status {
                Section {
                    Text(reason)
                    HStack {
                        Button("Microphone Settings") { Permissions.open(.microphone) }
                        Button("Speech Recognition Settings") { Permissions.open(.speechRecognition) }
                    }
                }
            }
        }
        .formStyle(.grouped)
    }

    private var statusText: String {
        switch model.voice.status {
        case .off: return "Off"
        case .starting: return "Starting…"
        case .listening: return "Listening (on-device)"
        case .unavailable: return "Unavailable"
        }
    }
}

// MARK: - Imports

private struct ImportSettings: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        Form {
            Section {
                if model.settings.watchedFolders.isEmpty {
                    Text("No folders yet.").foregroundStyle(.secondary)
                }
                ForEach(model.settings.watchedFolders, id: \.self) { path in
                    HStack {
                        Image(systemName: "folder")
                        Text((path as NSString).abbreviatingWithTildeInPath)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Button("Remove") { model.removeWatchedFolder(path) }
                            .buttonStyle(.borderless)
                    }
                }
                Button("Add Folder…") { model.addWatchedFolder() }
            } header: {
                Text("Watched folders")
            } footer: {
                Text("New videos saved to these folders (by OBS or any other recorder) are imported into the selected session automatically. Clip That only reads the exported files. It doesn't control those apps. Files already in the folder aren't imported; use Import Clips… for those.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
    }
}

// MARK: - Permissions

private struct PermissionSettings: View {
    @State private var refresh = 0

    var body: some View {
        Form {
            Section {
                row("Screen & System Audio Recording", Permissions.screenRecording,
                    detail: "Needed for the replay buffer.", pane: .screenRecording) {
                    Permissions.requestScreenRecording()
                }
                row("Microphone", Permissions.microphone,
                    detail: "Needed for the voice trigger and, if you turn it on, mic audio in clips.", pane: .microphone) {
                    Task { _ = await Permissions.requestMicrophone(); refresh += 1 }
                }
                row("Speech Recognition", Permissions.speechRecognition,
                    detail: "Needed to recognize “Clip that” on-device.", pane: .speechRecognition) {
                    Task { _ = await Permissions.requestSpeechRecognition(); refresh += 1 }
                }
            } footer: {
                Text("After allowing Screen Recording in System Settings, macOS may ask you to reopen Clip That.")
                    .foregroundStyle(.secondary)
            }
            Section {
                Button("Check Again") { refresh += 1 }
            }
        }
        .formStyle(.grouped)
        .id(refresh)
    }

    private func row(_ title: String, _ state: PermissionState, detail: String, pane: PrivacyPane,
                     request: @escaping () -> Void) -> some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                Text(detail).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(state.label).foregroundStyle(state == .granted ? Color.green : Color.secondary)
            if state == .notDetermined {
                Button("Allow…") { request(); refresh += 1 }
            } else if state != .granted {
                Button("Open Settings") { Permissions.open(pane) }
            }
        }
    }
}

// MARK: - Engine

private struct EngineSettings: View {
    @EnvironmentObject private var model: AppModel
    @State private var python = ""
    @State private var ffmpeg = ""
    @State private var editor = ""

    var body: some View {
        Form {
            Section {
                if model.toolChecks.isEmpty {
                    ProgressView().controlSize(.small)
                }
                ForEach(model.toolChecks) { check in
                    HStack(alignment: .firstTextBaseline) {
                        Image(systemName: check.ok ? "checkmark.circle.fill" : "xmark.octagon.fill")
                            .foregroundStyle(check.ok ? Color.green : Color.red)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(check.name)
                            Text(check.detail).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                    }
                }
                Button("Check Again") { model.refreshToolChecks() }
            } header: {
                Text("Render engine")
            } footer: {
                Text("Rendering runs the bundled clipthat_editor with Python and FFmpeg on this Mac. Install missing pieces with Homebrew: brew install python ffmpeg")
                    .foregroundStyle(.secondary)
            }

            Section("Overrides (leave blank to auto-detect)") {
                TextField("Python 3 path", text: $python, prompt: Text("/opt/homebrew/bin/python3"))
                TextField("FFmpeg path", text: $ffmpeg, prompt: Text("/opt/homebrew/bin/ffmpeg"))
                TextField("Editor folder", text: $editor, prompt: Text("Folder containing clipthat_editor"))
                Button("Apply") {
                    model.settings.toolOverrides = ToolOverrides(pythonPath: python.nilIfBlank,
                                                                 ffmpegPath: ffmpeg.nilIfBlank,
                                                                 editorPath: editor.nilIfBlank)
                }
            }

            Section("Library") {
                LabeledContent("Sessions folder") {
                    Text((model.store.root.path as NSString).abbreviatingWithTildeInPath).textSelection(.enabled)
                }
                Button("Show in Finder") { model.revealLibrary() }
            }
        }
        .formStyle(.grouped)
        .onAppear {
            python = model.settings.toolOverrides.pythonPath ?? ""
            ffmpeg = model.settings.toolOverrides.ffmpegPath ?? ""
            editor = model.settings.toolOverrides.editorPath ?? ""
        }
    }
}

private extension String {
    var nilIfBlank: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
