"""
Global Hotkey Handler - Uses CGEventTap to capture Cmd+Option+V.
"""

from typing import Callable, Optional

import Quartz
from Quartz import (
    CGEventTapCreate,
    CGEventTapEnable,
    CGEventMaskBit,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventTapOptionDefault,
    kCGEventKeyDown,
    kCGEventFlagsChanged,
)
from AppKit import (
    NSApp,
    NSEvent,
    NSCommandKeyMask,
    NSAlternateKeyMask,
)
import threading


# Key code for 'V'
KEY_V = 9


class HotkeyHandler:
    """
    Handles global hotkey detection using CGEventTap.
    Detects Cmd+Option+V to trigger the clipboard popup.
    """
    
    def __init__(self, on_trigger: Optional[Callable[[], None]] = None, 
                 on_permission_denied: Optional[Callable[[], None]] = None,
                 debug: bool = False):
        self.on_trigger = on_trigger
        self.on_permission_denied = on_permission_denied
        self.debug = debug
        self._tap = None
        self._run_loop_source = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._permission_denied = False
    
    def start(self):
        """Start listening for hotkeys in a background thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_event_tap, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop the hotkey listener."""
        self._running = False
        if self._tap:
            CFRunLoopStop(CFRunLoopGetCurrent())
    
    def _run_event_tap(self):
        """Set up and run the event tap."""
        print("[HotkeyHandler] Creating event tap...")
        
        # Create event mask for key down events
        event_mask = CGEventMaskBit(kCGEventKeyDown)
        
        # Create the event tap
        self._tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            event_mask,
            self._event_callback,
            None
        )
        
        if self._tap is None:
            print("[HotkeyHandler] ERROR: Failed to create event tap!")
            print("[HotkeyHandler] Please grant Accessibility permission in System Settings > Privacy & Security > Accessibility")
            self._permission_denied = True
            if self.on_permission_denied:
                self.on_permission_denied()
            return
        
        print("[HotkeyHandler] Event tap created successfully!")
        
        # Create run loop source and add to current run loop
        self._run_loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        CFRunLoopAddSource(
            CFRunLoopGetCurrent(),
            self._run_loop_source,
            Quartz.kCFRunLoopCommonModes
        )
        
        # Enable the tap
        CGEventTapEnable(self._tap, True)
        
        print("[HotkeyHandler] ✓ Hotkey handler started. Listening for Cmd+Option+V...")
        print("[HotkeyHandler] Running event loop...")
        
        # Run the loop
        CFRunLoopRun()
        print("[HotkeyHandler] Event loop ended.")
    
    def _event_callback(self, proxy, event_type, event, refcon):
        """Callback for keyboard events."""
        try:
            if event_type == kCGEventKeyDown:
                # Get key code
                key_code = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode
                )
                
                # Get modifier flags
                flags = Quartz.CGEventGetFlags(event)
                
                # Let Ctrl+C quit the app (key code 8 = 'C')
                ctrl_pressed = bool(flags & Quartz.kCGEventFlagMaskControl)
                if key_code == 8 and ctrl_pressed:
                    print("\n[HotkeyHandler] Ctrl+C detected, quitting...")
                    NSApp.terminate_(None)
                    return None
                
                # Check for Cmd+Option+V
                cmd_pressed = bool(flags & Quartz.kCGEventFlagMaskCommand)
                alt_pressed = bool(flags & Quartz.kCGEventFlagMaskAlternate)
                
                # Log key presses ONLY in debug mode to prevent keylogging behavior
                if self.debug:
                    print(f"[HotkeyHandler] Key pressed: code={key_code}, cmd={cmd_pressed}, alt={alt_pressed}")
                
                if key_code == KEY_V and cmd_pressed and alt_pressed:
                    print("[HotkeyHandler] *** HOTKEY DETECTED: Cmd+Option+V ***")
                    if self.on_trigger:
                        # Call on main thread
                        self.on_trigger()
                    # Suppress the event so it doesn't propagate
                    return None
        except Exception as e:
            print(f"[HotkeyHandler] Callback error: {e}")
        
        return event
