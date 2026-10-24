import AppKit
import ClipThatCore
import Combine
import SwiftUI
import UniformTypeIdentifiers

// MARK: - Settings

struct AppSettings: Codable, Equatable {
    var bufferSeconds: Double = 30
    var postRollSeconds: Double = 1.5
    var captureFPS: Int = 60
    var captureMaxHeight: Int = 1080
    var includeMicrophone = false
    var mixMicIntoClip = true
    var excludedBundleIDs: [String] = []
    var hotkey: HotkeyChoice = .controlOptionC
    var playSounds = true
    var watchedFolders: [String] = []
    var toolOverrides = ToolOverrides()

    private static let key = "settings.v1"

    static func load() -> AppSettings {
        guard let data = UserDefaults.standard.data(forKey: key),
              let value = try? JSONDecoder().decode(AppSettings.self, from: data) else { return AppSettings() }
        return value
    }

    func save() {
        if let data = try? JSONEncoder().encode(self) { UserDefaults.standard.set(data, forKey: Self.key) }
    }
}

extension AppSettings {
    /// Tolerates missing keys so adding a setting never resets the others.
    init(from decoder: Decoder) throws {
        self.init()
        let c = try decoder.container(keyedBy: CodingKeys.self)
        bufferSeconds = try c.decodeIfPresent(Double.self, forKey: .bufferSeconds) ?? bufferSeconds
        postRollSeconds = try c.decodeIfPresent(Double.self, forKey: .postRollSeconds) ?? postRollSeconds
        captureFPS = try c.decodeIfPresent(Int.self, forKey: .captureFPS) ?? captureFPS
        captureMaxHeight = try c.decodeIfPresent(Int.self, forKey: .captureMaxHeight) ?? captureMaxHeight
        includeMicrophone = try c.decodeIfPresent(Bool.self, forKey: .includeMicrophone) ?? includeMicrophone
        mixMicIntoClip = try c.decodeIfPresent(Bool.self, forKey: .mixMicIntoClip) ?? mixMicIntoClip
        excludedBundleIDs = try c.decodeIfPresent([String].self, forKey: .excludedBundleIDs) ?? excludedBundleIDs
        hotkey = (try? c.decodeIfPresent(HotkeyChoice.self, forKey: .hotkey)) ?? hotkey
        playSounds = try c.decodeIfPresent(Bool.self, forKey: .playSounds) ?? playSounds
        watchedFolders = try c.decodeIfPresent([String].self, forKey: .watchedFolders) ?? watchedFolders
        toolOverrides = try c.decodeIfPresent(ToolOverrides.self, forKey: .toolOverrides) ?? toolOverrides
    }
}

// MARK: - UI state

enum RenderState: Equatable {
    case idle
    case rendering(sessionID: String, startedAt: Date)
    case finished(sessionID: String, output: URL)
    case failed(sessionID: String, message: String, log: String)

    var sessionID: String? {
        switch self {
        case .idle: return nil
        case .rendering(let id, _), .finished(let id, _), .failed(let id, _, _): return id
        }
    }
}

struct Banner: Identifiable, Equatable {
    let id = UUID()
    var text: String
    var isError: Bool
}

// MARK: - App model

@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()

    let store: SessionStore
    let recorder = ReplayRecorder()
    let voice = VoiceTrigger()

    @Published private(set) var sessions: [Session] = []
    @Published var selectedSessionID: String? {
        didSet { if oldValue != selectedSessionID { selectedClipID = selectedSession?.clips.first?.id } }
    }
    @Published var selectedClipID: String?
    @Published private(set) var tools: ToolLocations
    @Published private(set) var toolChecks: [ToolCheck] = []
    @Published private(set) var renderState: RenderState = .idle
    @Published private(set) var banner: Banner?
    @Published private(set) var importsInFlight = 0
    @Published private(set) var replayStatus: ReplayRecorder.Status = .off
    @Published private(set) var bufferedSeconds: Double = 0
    @Published private(set) var savingClips = 0
    @Published private(set) var hotkeyRegistered = false
    /// Clips currently being analyzed for a suggested trim.
    @Published private(set) var analyzingClipIDs: Set<String> = []
    /// Target length for suggested trims, in seconds.
    @Published var autoTrimLength: Double = 8
    @Published var settings: AppSettings {
        didSet { settingsChanged(from: oldValue) }
    }

    private var hotkey: GlobalHotkey?
    private var renderTask: Task<Void, Never>?
    private var watchTask: Task<Void, Never>?
    private var bannerTask: Task<Void, Never>?
    private let scanner = FolderScanner()
    private var voiceForwarding: AnyCancellable?
    private var launchObserver: NSObjectProtocol?

    private init() {
        let loaded = AppSettings.load()
        settings = loaded
        store = SessionStore(root: SessionStore.defaultRoot())
        tools = Toolchain.locate(overrides: loaded.toolOverrides, bundledEditor: Self.bundledEditor)
        sessions = store.loadAll()
        selectedSessionID = sessions.first?.id
        selectedClipID = sessions.first?.clips.first?.id

        ReplayRecorder.wipeStaleBuffers()
        recorder.onStatusChange = { [weak self] status, seconds in
            Task { @MainActor in
                self?.replayStatus = status
                self?.bufferedSeconds = seconds
            }
        }
        voice.onTrigger = { [weak self] in self?.clipThat(trigger: .voice) }
        voiceForwarding = voice.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }
        launchObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didLaunchApplicationNotification, object: nil, queue: .main) { [weak self] note in
            let bundleID = (note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication)?.bundleIdentifier
            Task { @MainActor in self?.appLaunched(bundleID) }
        }

        registerHotkey()
        restartWatching()
        refreshToolChecks()
    }

    static var bundledEditor: URL? {
        Bundle.main.resourceURL?.appendingPathComponent("editor", isDirectory: true)
    }

    // MARK: Sessions

    var selectedSession: Session? { session(selectedSessionID) }

    func session(_ id: String?) -> Session? {
        guard let id else { return nil }
        return sessions.first { $0.id == id }
    }

    func clipURL(_ clip: Clip, in session: Session) -> URL {
        store.url(for: clip, in: session)
    }

    func fileURL(_ relativePath: String, in session: Session) -> URL {
        store.url(relativePath, in: session)
    }

    @discardableResult
    func newSession() -> Session? {
        do {
            let session = try store.create()
            sessions.insert(session, at: 0)
            selectedSessionID = session.id
            return session
        } catch {
            show(error)
            return nil
        }
    }

    func rename(_ id: String, to title: String) {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        update(id) { $0.title = trimmed }
    }

    /// Moves the session folder to the Trash (recoverable).
    func deleteSession(_ id: String) {
        guard let session = session(id) else { return }
        do {
            try store.delete(session)
            sessions.removeAll { $0.id == id }
            if selectedSessionID == id { selectedSessionID = sessions.first?.id }
            show("Moved “\(session.title)” to the Trash.")
        } catch {
            show(error)
        }
    }

    /// Where captures and folder imports land: the selected session, or a new one.
    private func captureTarget() -> Session? {
        selectedSession ?? newSession()
    }

    private func update(_ id: String, _ body: (inout Session) -> Void) {
        guard let index = sessions.firstIndex(where: { $0.id == id }) else { return }
        body(&sessions[index])
        do {
            try store.save(sessions[index])
        } catch {
            show(error)
        }
    }

    // MARK: Clips

    func importFiles(_ urls: [URL], origin: ClipOrigin = .fileImport, label: String? = nil) {
        let supported = urls.filter(ClipImporter.isSupported)
        if supported.count < urls.count {
            show("Skipped \(urls.count - supported.count) file(s) that aren't videos Clip That can read.", error: true)
        }
        guard !supported.isEmpty, let target = captureTarget() else { return }
        for url in supported {
            importsInFlight += 1
            let store = self.store
            let tools = self.tools
            Task {
                defer { importsInFlight -= 1 }
                do {
                    let clip = try await ClipImporter.importFile(url, into: target, store: store, tools: tools,
                                                                 origin: origin, importedFrom: label)
                    update(target.id) { $0.clips.append(clip) }
                    if selectedSessionID == target.id, selectedClipID == nil { selectedClipID = clip.id }
                    if origin == .folderImport { show("Imported “\(url.lastPathComponent)” from \(label ?? "folder").") }
                } catch {
                    show("Couldn't import “\(url.lastPathComponent)”: \(error.localizedDescription)", error: true)
                }
            }
        }
    }

    func presentImportPanel() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.message = "Choose clips exported by your recorder (MP4, MOV, MKV…)"
        panel.allowedContentTypes = Self.importTypes
        if panel.runModal() == .OK { importFiles(panel.urls) }
    }

    static var importTypes: [UTType] {
        [.movie, .mpeg4Movie, .quickTimeMovie] + ClipImporter.remuxExtensions.compactMap { UTType(filenameExtension: $0) }
    }

    /// Moves the clip file to the Trash and removes it from the session.
    func removeClip(_ clipID: String, from sessionID: String) {
        guard let session = session(sessionID), let clip = session.clips.first(where: { $0.id == clipID }) else { return }
        do {
            try store.discardFile(clip.relativePath, in: session)
        } catch {
            show(error)
            return
        }
        update(sessionID) { $0.clips.removeAll { $0.id == clipID } }
        if selectedClipID == clipID { selectedClipID = self.session(sessionID)?.clips.first?.id }
    }

    func moveClips(in sessionID: String, from offsets: IndexSet, to destination: Int) {
        update(sessionID) { $0.clips.move(fromOffsets: offsets, toOffset: destination) }
    }

    func moveClip(_ clipID: String, in sessionID: String, by delta: Int) {
        guard let session = session(sessionID), let index = session.clips.firstIndex(where: { $0.id == clipID }) else { return }
        let target = index + delta
        guard session.clips.indices.contains(target) else { return }
        update(sessionID) { $0.clips.swapAt(index, target) }
    }

    func setSelection(_ clipID: String, in sessionID: String, start: Double, duration: Double) {
        update(sessionID) { session in
            guard let i = session.clips.firstIndex(where: { $0.id == clipID }) else { return }
            let sel = ClipSelection.normalized(start: start, duration: duration, mediaDuration: session.clips[i].mediaDuration)
            session.clips[i].selectionStart = sel.start
            session.clips[i].selectionDuration = sel.duration
        }
    }

    func resetSelection(_ clipID: String, in sessionID: String) {
        update(sessionID) { session in
            guard let i = session.clips.firstIndex(where: { $0.id == clipID }) else { return }
            let sel = ClipSelection.defaultSelection(mediaDuration: session.clips[i].mediaDuration)
            session.clips[i].selectionStart = sel.start
            session.clips[i].selectionDuration = sel.duration
        }
    }

    // MARK: Suggested trims

    /// Trims a clip around its key moment. Replay clips pass their trigger time, so the
    /// analyzer only searches the seconds before "Clip that" was said.
    func suggestTrim(_ clipID: String, in sessionID: String) {
        guard let session = session(sessionID), let clip = session.clips.first(where: { $0.id == clipID }),
              !analyzingClipIDs.contains(clipID) else { return }
        analyzingClipIDs.insert(clipID)
        let url = store.url(for: clip, in: session)
        let tools = self.tools
        let length = autoTrimLength
        Task {
            defer { analyzingClipIDs.remove(clipID) }
            do {
                let s = try await ClipAnalyzer.suggest(for: url, length: length, triggerOffset: clip.triggerOffset, tools: tools)
                setSelection(clipID, in: sessionID, start: s.suggestedStart, duration: s.suggestedDuration)
                show("Trimmed to \(DurationFormat.short(s.suggestedDuration)) around \(DurationFormat.clock(s.peakTime)). “Use Whole Clip” undoes it.")
            } catch {
                show(error)
            }
        }
    }

    /// Suggested trims for every clip in the session, one at a time.
    func autoTrimAll(in sessionID: String) {
        guard let session = session(sessionID), analyzingClipIDs.isEmpty else { return }
        let jobs = session.clips.map { ($0.id, store.url(for: $0, in: session), $0.triggerOffset) }
        let tools = self.tools
        let length = autoTrimLength
        analyzingClipIDs = Set(jobs.map { $0.0 })
        Task {
            var done = 0
            for (clipID, url, trigger) in jobs {
                defer { analyzingClipIDs.remove(clipID) }
                do {
                    let s = try await ClipAnalyzer.suggest(for: url, length: length, triggerOffset: trigger, tools: tools)
                    setSelection(clipID, in: sessionID, start: s.suggestedStart, duration: s.suggestedDuration)
                    done += 1
                } catch {
                    show(error)
                }
            }
            if done > 0 { show("Trimmed \(done) clip\(done == 1 ? "" : "s") to about \(Int(length)) s each.") }
        }
    }

    // MARK: Render settings

    func setStyle(_ style: RenderStyle, for sessionID: String) {
        update(sessionID) { $0.settings.style = style }
    }

    func setLayout(_ layout: RenderLayout, for sessionID: String) {
        update(sessionID) { $0.settings.layout = layout }
    }

    func setMusicVolume(_ volume: Double, for sessionID: String) {
        update(sessionID) { $0.settings.musicVolume = min(max(volume, 0), 1) }
    }

    func chooseMusic(for sessionID: String) {
        guard let session = session(sessionID) else { return }
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.audio]
        panel.message = "Choose a soundtrack you have the rights to use."
        guard panel.runModal() == .OK, let source = panel.url else { return }
        do {
            let dest = try store.uniqueDestination(in: session, folder: "music",
                                                   baseName: source.deletingPathExtension().lastPathComponent,
                                                   ext: source.pathExtension.isEmpty ? "m4a" : source.pathExtension)
            try FileManager.default.copyItem(at: source, to: dest.url)
            update(sessionID) { $0.settings.musicRelativePath = dest.relativePath }
        } catch {
            show(error)
        }
    }

    func removeMusic(for sessionID: String) {
        update(sessionID) { $0.settings.musicRelativePath = nil }
    }

    // MARK: Render / export

    var isRendering: Bool {
        if case .rendering = renderState { return true }
        return false
    }

    func render(_ sessionID: String) {
        guard !isRendering, let session = session(sessionID) else { return }
        renderState = .rendering(sessionID: sessionID, startedAt: Date())
        let store = self.store
        let tools = self.tools
        renderTask = Task {
            do {
                let (result, record) = try await Renderer.render(session: session, store: store, tools: tools)
                update(sessionID) { $0.renders.insert(record, at: 0) }
                renderState = .finished(sessionID: sessionID, output: result.output)
                if settings.playSounds { NSSound(named: "Glass")?.play() }
            } catch let failure as RenderFailure {
                if failure == .cancelled {
                    renderState = .idle
                } else {
                    renderState = .failed(sessionID: sessionID, message: failure.localizedDescription, log: failure.log)
                }
            } catch {
                renderState = .failed(sessionID: sessionID, message: error.localizedDescription, log: "")
            }
        }
    }

    func cancelRender() {
        renderTask?.cancel()
    }

    func dismissRenderResult() {
        if !isRendering { renderState = .idle }
    }

    /// Copies a finished montage wherever the user wants. Nothing is uploaded or posted.
    func export(_ url: URL, suggestedName: String) {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.mpeg4Movie]
        panel.nameFieldStringValue = SessionStore.sanitize(suggestedName) + ".mp4"
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let dest = panel.url else { return }
        do {
            if FileManager.default.fileExists(atPath: dest.path) { try FileManager.default.removeItem(at: dest) }
            try FileManager.default.copyItem(at: url, to: dest)
            show("Exported to \(dest.deletingLastPathComponent().lastPathComponent)/\(dest.lastPathComponent).")
        } catch {
            show(error)
        }
    }

    func reveal(_ url: URL) {
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    func revealLibrary() {
        try? FileManager.default.createDirectory(at: store.sessionsDirectory, withIntermediateDirectories: true)
        NSWorkspace.shared.activateFileViewerSelecting([store.root])
    }

    // MARK: Capture

    var replayIsActive: Bool {
        switch replayStatus {
        case .starting, .buffering, .paused: return true
        case .off, .failed: return false
        }
    }

    func setReplayEnabled(_ on: Bool) {
        Task {
            guard on else {
                await recorder.stop()
                return
            }
            if Permissions.screenRecording != .granted {
                Permissions.requestScreenRecording()
                if Permissions.screenRecording != .granted {
                    replayStatus = .failed(ReplayError.permissionDenied.localizedDescription)
                    return
                }
            }
            var micAllowed = settings.includeMicrophone
            if micAllowed && Permissions.microphone != .granted {
                micAllowed = Permissions.microphone == .notDetermined ? await Permissions.requestMicrophone() : false
                if !micAllowed {
                    show("Microphone access is off, so clips won't include your mic. Allow it in System Settings → Privacy & Security → Microphone.", error: true)
                }
            }
            let config = ReplayConfiguration(bufferSeconds: settings.bufferSeconds,
                                             postRollSeconds: settings.postRollSeconds,
                                             fps: settings.captureFPS, maxHeight: settings.captureMaxHeight,
                                             includeMicrophone: micAllowed,
                                             excludedBundleIDs: settings.excludedBundleIDs)
            do {
                try await recorder.start(config)
            } catch {
                replayStatus = .failed(error.localizedDescription)
            }
        }
    }

    func setReplayPaused(_ paused: Bool) {
        recorder.setPaused(paused)
    }

    /// The "Clip that" action, from voice, hotkey or button.
    func clipThat(trigger: ClipTrigger) {
        guard replayStatus == .buffering else {
            let reason = replayStatus == .paused ? ReplayError.paused : ReplayError.notRunning
            show(reason.localizedDescription, error: true)
            if settings.playSounds { NSSound(named: "Basso")?.play() }
            return
        }
        guard let target = captureTarget() else { return }
        if settings.playSounds { NSSound(named: "Tink")?.play() }
        savingClips += 1
        let tools = self.tools
        let mix = settings.mixMicIntoClip
        Task {
            defer { savingClips -= 1 }
            do {
                let saved = try await recorder.saveClip(tools: tools, mixMicIntoMain: mix)
                let clip = try await adoptReplay(saved, trigger: trigger, into: target)
                update(target.id) { $0.clips.append(clip) }
                if selectedSessionID == target.id { selectedClipID = clip.id }
                show("Saved a \(DurationFormat.clock(clip.mediaDuration)) clip to “\(target.title)”.")
            } catch {
                show(error)
                if settings.playSounds { NSSound(named: "Basso")?.play() }
            }
        }
    }

    private func adoptReplay(_ saved: SavedReplay, trigger: ClipTrigger, into session: Session) async throws -> Clip {
        let dest = try store.uniqueDestination(in: session, folder: "clips",
                                               baseName: "replay-\(SessionStore.stamp(saved.capturedAt))-\(trigger.rawValue)",
                                               ext: "mp4")
        try FileManager.default.moveItem(at: saved.url, to: dest.url)
        let info = try await MediaProbe.probe(dest.url, tools: tools)
        return Clip(relativePath: dest.relativePath, origin: .replay, trigger: trigger,
                    capturedAt: saved.capturedAt, mediaDuration: info.duration,
                    triggerOffset: min(saved.triggerOffset, info.duration),
                    hasAudio: info.hasAudio, hasMicTrack: saved.plan.microphone && info.audioStreamCount > 1)
    }

    func setVoiceEnabled(_ on: Bool) {
        if on {
            Task { await voice.start() }
        } else {
            voice.stop()
        }
    }

    var voiceIsOn: Bool {
        voice.status == .listening || voice.status == .starting
    }

    private func registerHotkey() {
        hotkey = nil
        hotkey = GlobalHotkey(settings.hotkey) { [weak self] in
            Task { @MainActor in self?.clipThat(trigger: .hotkey) }
        }
        hotkeyRegistered = hotkey != nil
        if hotkey == nil {
            show("\(settings.hotkey.label) is already used by another app. Pick a different shortcut in Settings.", error: true)
        }
    }

    private func appLaunched(_ bundleID: String?) {
        guard let bundleID, settings.excludedBundleIDs.contains(bundleID), replayIsActive else { return }
        let excluded = settings.excludedBundleIDs
        Task { await recorder.refreshExclusions(excluded) }
    }

    // MARK: Watched folders

    func addWatchedFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = "Choose the folder your recorder saves clips to (for OBS, see Settings → Output → Recording Path)."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        if !settings.watchedFolders.contains(url.path) { settings.watchedFolders.append(url.path) }
    }

    func removeWatchedFolder(_ path: String) {
        settings.watchedFolders.removeAll { $0 == path }
    }

    private func restartWatching() {
        watchTask?.cancel()
        watchTask = nil
        guard !settings.watchedFolders.isEmpty else { return }
        watchTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                let folders = self.settings.watchedFolders.map { URL(fileURLWithPath: $0, isDirectory: true) }
                for file in self.scanner.poll(folders) {
                    self.importFiles([file], origin: .folderImport, label: file.deletingLastPathComponent().lastPathComponent)
                }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }

    // MARK: Tools

    func refreshToolChecks() {
        tools = Toolchain.locate(overrides: settings.toolOverrides, bundledEditor: Self.bundledEditor)
        let snapshot = tools
        Task { toolChecks = await Toolchain.check(snapshot) }
    }

    // MARK: Settings

    private func settingsChanged(from old: AppSettings) {
        settings.save()
        if old.hotkey != settings.hotkey { registerHotkey() }
        if old.watchedFolders != settings.watchedFolders { restartWatching() }
        if old.toolOverrides != settings.toolOverrides { refreshToolChecks() }
        if old.excludedBundleIDs != settings.excludedBundleIDs, replayIsActive {
            let excluded = settings.excludedBundleIDs
            Task { await recorder.refreshExclusions(excluded) }
        }
        let captureChanged = old.bufferSeconds != settings.bufferSeconds || old.captureFPS != settings.captureFPS
            || old.captureMaxHeight != settings.captureMaxHeight || old.includeMicrophone != settings.includeMicrophone
            || old.postRollSeconds != settings.postRollSeconds
        if captureChanged && replayIsActive {
            show("Turn the replay buffer off and on to apply the new capture settings.")
        }
    }

    // MARK: Shutdown

    func shutdown() async {
        voice.stop()
        renderTask?.cancel()
        await recorder.stop()
    }

    // MARK: Banners

    func show(_ text: String, error: Bool = false) {
        banner = Banner(text: text, isError: error)
        bannerTask?.cancel()
        bannerTask = Task {
            try? await Task.sleep(nanoseconds: error ? 7_000_000_000 : 4_000_000_000)
            if !Task.isCancelled { banner = nil }
        }
    }

    func show(_ error: Error) {
        show(error.localizedDescription, error: true)
    }

    func dismissBanner() {
        banner = nil
    }
}
