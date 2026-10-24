import AVFoundation
import ClipThatCore
import Speech

/// Listens to the microphone and fires when the user says "Clip that".
///
/// Privacy: on-device recognition only (`requiresOnDeviceRecognition`). If the Mac
/// can't recognize speech on-device, the trigger reports unavailable rather than
/// sending audio to a server. Nothing is recorded or stored by this class.
///
/// Recognition tasks are restarted after each trigger and every ~50 s so transcripts
/// stay short and long sessions don't hit recognizer limits.
@MainActor
final class VoiceTrigger: ObservableObject {
    enum Status: Equatable {
        case off
        case starting
        case listening
        case unavailable(String)
    }

    @Published private(set) var status: Status = .off
    /// Tail of what the recognizer heard (shown in Settings to help debug false triggers).
    @Published private(set) var lastHeard = ""

    var onTrigger: (() -> Void)?

    private let engine = AVAudioEngine()
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let forwarder = TapForwarder()
    private var task: SFSpeechRecognitionTask?
    private var spotter = PhraseSpotter()
    private var generation = 0
    private var refreshTimer: Timer?
    private var configObserver: NSObjectProtocol?
    private var tapInstalled = false
    private var lastHeardUpdate: TimeInterval = 0

    func start() async {
        guard status == .off || status.isUnavailable else { return }
        status = .starting

        guard await ensurePermissions() else {
            status = .unavailable("Microphone and Speech Recognition access are needed. Allow them in System Settings → Privacy & Security.")
            return
        }
        guard let recognizer else {
            status = .unavailable("Speech recognition isn't available for English (US) on this Mac.")
            return
        }
        guard recognizer.supportsOnDeviceRecognition else {
            status = .unavailable("On-device speech recognition isn't installed. In System Settings → Keyboard → Dictation, turn on Dictation once to download it, then try again.")
            return
        }
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            status = .unavailable("No microphone input found.")
            return
        }
        Self.installTap(on: input, format: format, forwarder: forwarder)
        tapInstalled = true
        engine.prepare()
        do {
            try engine.start()
        } catch {
            teardownAudio()
            status = .unavailable("Couldn't start the microphone: \(error.localizedDescription)")
            return
        }
        configObserver = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange,
                                                                object: engine, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.handleDeviceChange() }
        }
        startTask()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 50, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.restartTask() }
        }
        status = .listening
    }

    func stop() {
        refreshTimer?.invalidate()
        refreshTimer = nil
        if let configObserver { NotificationCenter.default.removeObserver(configObserver) }
        configObserver = nil
        generation += 1
        forwarder.swap(nil)?.endAudio()
        task?.cancel()
        task = nil
        teardownAudio()
        status = .off
        lastHeard = ""
    }

    // MARK: Recognition

    private func startTask() {
        guard let recognizer else { return }
        generation += 1
        let current = generation
        spotter.reset()
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = true
        request.addsPunctuation = false
        request.taskHint = .dictation
        request.contextualStrings = ["clip that", "Clip that"]
        forwarder.swap(request)?.endAudio()
        task = Self.makeTask(recognizer: recognizer, request: request) { [weak self] text, isFinal, failed in
            Task { @MainActor in self?.handle(text: text, isFinal: isFinal, failed: failed, generation: current) }
        }
    }

    private func restartTask() {
        guard status == .listening || status == .starting else { return }
        task?.cancel()
        task = nil
        startTask()
    }

    private func handle(text: String?, isFinal: Bool, failed: Bool, generation: Int) {
        guard generation == self.generation, status == .listening else { return }
        if let text {
            let now = ProcessInfo.processInfo.systemUptime
            // lastHeard is only for the Settings readout; throttle it so the UI doesn't
            // re-render on every partial result while the user is talking mid-game.
            if now - lastHeardUpdate > 0.75 {
                lastHeard = String(text.suffix(80))
                lastHeardUpdate = now
            }
            if spotter.process(text, at: now) {
                onTrigger?()
                restartTask()
                return
            }
        }
        if isFinal || failed {
            // On-device tasks end after silence; start a fresh one.
            Task { @MainActor [weak self] in
                try? await Task.sleep(nanoseconds: 300_000_000)
                guard let self, generation == self.generation else { return }
                self.restartTask()
            }
        }
    }

    private func handleDeviceChange() {
        // Headset plugged/unplugged: the engine stops and the input format may change.
        guard status == .listening else { return }
        stop()
        Task { await start() }
    }

    private func teardownAudio() {
        engine.stop()
        if tapInstalled {
            engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
    }

    private func ensurePermissions() async -> Bool {
        var mic = Permissions.microphone == .granted
        if Permissions.microphone == .notDetermined { mic = await Permissions.requestMicrophone() }
        var speech = Permissions.speechRecognition == .granted
        if Permissions.speechRecognition == .notDetermined { speech = await Permissions.requestSpeechRecognition() }
        return mic && speech
    }

    // MARK: Non-isolated plumbing (runs on audio/recognizer threads)

    nonisolated private static func installTap(on node: AVAudioInputNode, format: AVAudioFormat, forwarder: TapForwarder) {
        node.installTap(onBus: 0, bufferSize: 2048, format: format) { buffer, _ in
            forwarder.append(buffer)
        }
    }

    nonisolated private static func makeTask(recognizer: SFSpeechRecognizer,
                                             request: SFSpeechAudioBufferRecognitionRequest,
                                             handler: @escaping @Sendable (String?, Bool, Bool) -> Void) -> SFSpeechRecognitionTask {
        recognizer.recognitionTask(with: request) { result, error in
            handler(result?.bestTranscription.formattedString, result?.isFinal ?? false, error != nil)
        }
    }
}

private extension VoiceTrigger.Status {
    var isUnavailable: Bool {
        if case .unavailable = self { return true }
        return false
    }
}

/// Hands audio buffers from the realtime tap to whichever request is current.
private final class TapForwarder: @unchecked Sendable {
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?

    func append(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        let current = request
        lock.unlock()
        current?.append(buffer)
    }

    /// Installs a new request and returns the previous one.
    func swap(_ new: SFSpeechAudioBufferRecognitionRequest?) -> SFSpeechAudioBufferRecognitionRequest? {
        lock.lock()
        defer { lock.unlock() }
        let old = request
        request = new
        return old
    }
}
