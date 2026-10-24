import AppKit
import AVFoundation
import CoreGraphics
import Speech

enum PermissionState: Equatable {
    case granted
    case denied
    case notDetermined

    var label: String {
        switch self {
        case .granted: return "Allowed"
        case .denied: return "Not allowed"
        case .notDetermined: return "Not asked yet"
        }
    }
}

enum PrivacyPane {
    case screenRecording, microphone, speechRecognition

    var url: URL {
        let anchor: String
        switch self {
        case .screenRecording: anchor = "Privacy_ScreenCapture"
        case .microphone: anchor = "Privacy_Microphone"
        case .speechRecognition: anchor = "Privacy_SpeechRecognition"
        }
        return URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)")!
    }
}

enum Permissions {
    /// macOS doesn't distinguish "denied" from "never asked" for screen recording;
    /// preflight just says whether capture is currently allowed.
    static var screenRecording: PermissionState {
        CGPreflightScreenCaptureAccess() ? .granted : .notDetermined
    }

    /// Shows the system prompt the first time; afterwards the user must use System Settings.
    @discardableResult
    static func requestScreenRecording() -> Bool {
        CGRequestScreenCaptureAccess()
    }

    static var microphone: PermissionState {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return .granted
        case .notDetermined: return .notDetermined
        default: return .denied
        }
    }

    static func requestMicrophone() async -> Bool {
        await AVCaptureDevice.requestAccess(for: .audio)
    }

    static var speechRecognition: PermissionState {
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized: return .granted
        case .notDetermined: return .notDetermined
        default: return .denied
        }
    }

    static func requestSpeechRecognition() async -> Bool {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status == .authorized)
            }
        }
    }

    static func open(_ pane: PrivacyPane) {
        NSWorkspace.shared.open(pane.url)
    }
}
