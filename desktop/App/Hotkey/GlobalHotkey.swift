import Carbon.HIToolbox
import Foundation

/// Preset shortcuts for "Clip that". Carbon hotkeys work system-wide (including over
/// full-screen games) and, unlike event taps, need no Accessibility permission.
enum HotkeyChoice: String, Codable, CaseIterable, Identifiable {
    case controlOptionC
    case controlShiftC
    case optionShiftC
    case f9

    var id: String { rawValue }

    var label: String {
        switch self {
        case .controlOptionC: return "⌃⌥C"
        case .controlShiftC: return "⌃⇧C"
        case .optionShiftC: return "⌥⇧C"
        case .f9: return "F9"
        }
    }

    var keyCode: UInt32 {
        switch self {
        case .controlOptionC, .controlShiftC, .optionShiftC: return UInt32(kVK_ANSI_C)
        case .f9: return UInt32(kVK_F9)
        }
    }

    var carbonModifiers: UInt32 {
        switch self {
        case .controlOptionC: return UInt32(controlKey | optionKey)
        case .controlShiftC: return UInt32(controlKey | shiftKey)
        case .optionShiftC: return UInt32(optionKey | shiftKey)
        case .f9: return 0
        }
    }
}

final class GlobalHotkey {
    private var hotKeyRef: EventHotKeyRef?
    private var handlerRef: EventHandlerRef?
    private let action: () -> Void

    /// Registers immediately. Returns nil if the shortcut is taken by another app.
    init?(_ choice: HotkeyChoice, action: @escaping () -> Void) {
        self.action = action
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let context = Unmanaged.passUnretained(self).toOpaque()
        let installStatus = InstallEventHandler(GetApplicationEventTarget(), { _, _, userData in
            guard let userData else { return OSStatus(eventNotHandledErr) }
            let hotkey = Unmanaged<GlobalHotkey>.fromOpaque(userData).takeUnretainedValue()
            DispatchQueue.main.async { hotkey.action() }
            return noErr
        }, 1, &eventType, context, &handlerRef)
        guard installStatus == noErr else { return nil }

        let hotKeyID = EventHotKeyID(signature: OSType(0x434C_5054), id: 1) // 'CLPT'
        let registerStatus = RegisterEventHotKey(choice.keyCode, choice.carbonModifiers, hotKeyID,
                                                 GetApplicationEventTarget(), 0, &hotKeyRef)
        guard registerStatus == noErr else {
            if let handlerRef { RemoveEventHandler(handlerRef) }
            handlerRef = nil
            return nil
        }
    }

    deinit {
        if let hotKeyRef { UnregisterEventHotKey(hotKeyRef) }
        if let handlerRef { RemoveEventHandler(handlerRef) }
    }
}
