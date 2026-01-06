#!/usr/bin/env python3
"""
ClipX - Minimal Clipboard History for macOS

A modern clipboard history tracking app that shows a floating popup
near your cursor when you press Cmd+Option+V.
"""

import sys
import signal
import os

class DebugLogger:
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.filename = filename
        self.log = open(filename, 'a', encoding='utf-8', errors='replace', buffering=1)

    def write(self, message):
        # Write to file (always safe with utf-8)
        try:
            self.log.write(message)
            self.log.flush()
        except Exception:
            pass
            
        # Write to terminal (original stdout) - might trigger unicode error
        try:
            self.terminal.write(message)
            self.terminal.flush()
        except Exception:
            # Fallback: encode/decode to safe ascii or just skip
            try:
                safe_msg = message.encode('ascii', 'replace').decode('ascii')
                self.terminal.write(safe_msg)
            except Exception:
                pass

    def flush(self):
        try:
            self.terminal.flush()
            self.log.flush()
        except Exception:
            pass


from AppKit import (
    NSApplication,
    NSApp,
    NSObject,
    NSApplicationActivationPolicyAccessory,
    NSEvent,
    NSEventMaskKeyDown,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSMenu,
    NSMenuItem,
    NSImage,
    NSSize,
)
import objc

from clipboard_monitor import ClipboardMonitor
from hotkey_handler import HotkeyHandler
from accessibility import AccessibilityHelper, ElementRect
from popup_window import ClipboardPopup, calculate_popup_position, ITEM_HEIGHT, PADDING, POPUP_MAX_HEIGHT


class ClipXDelegate(NSObject):
    """Main application delegate."""
    
    def init(self):
        self = objc.super(ClipXDelegate, self).init()
        if self is None:
            return None
        
        self._clipboard_monitor = None
        self._hotkey_handler = None
        self._accessibility = None
        self._popup = None
        self._status_item = None
        self._popup_visible = False
        
        return self
    
    def applicationDidFinishLaunching_(self, notification):
        """Called when app is ready."""
        print("ClipX starting...", flush=True)
        
        self._setup_status_item()
        
        # Check accessibility permission
        self._accessibility = AccessibilityHelper()
        has_access = AccessibilityHelper.check_accessibility_permission()
        print(f"[Main] Accessibility permission: {has_access}", flush=True)
        if not has_access:
            print("\n⚠️  Accessibility permission required!")
            print("   Go to: System Settings > Privacy & Security > Accessibility")
            print("   Enable access for Terminal or your Python environment.\n", flush=True)
        
        # Create popup
        print("[Main] Creating popup window...", flush=True)
        self._popup = ClipboardPopup.create(on_select=self._on_item_selected)
        print("[Main] Popup created.", flush=True)
        
        # Start clipboard monitor
        print("[Main] Starting clipboard monitor...", flush=True)
        self._clipboard_monitor = ClipboardMonitor(on_change=self._on_clipboard_change)
        self._clipboard_monitor.start()
        print("✓ Clipboard monitoring started", flush=True)
        
        # Start hotkey handler
        print("[Main] Starting hotkey handler...", flush=True)
        self._hotkey_handler = HotkeyHandler(on_trigger=self._on_hotkey_trigger)
        self._hotkey_handler.start()
        print("[Main] Hotkey handler started.", flush=True)
        
        # Add global key event monitor for when popup is visible
        self._setup_key_monitor()
        
        print("\n🚀 ClipX is running!")
        print("   • Copy text anywhere (Cmd+C) to add to history")
        print("   • Press Cmd+Option+V to show history popup")
        print("   • Press Ctrl+C in terminal to quit\n", flush=True)
    
    def _setup_status_item(self):
        """Create the menu bar item."""
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        
        # Try to find icon in bundle resources first (packaged app), then CWD
        from Foundation import NSBundle
        path = NSBundle.mainBundle().pathForResource_ofType_("icon", "icns")
        if not path:
             path = "icon.icns"
             
        image = NSImage.alloc().initByReferencingFile_(path)
        if image and image.isValid():
            image.setSize_(NSSize(18, 18))
            # image.setTemplate_(True) # Uncomment if icon is a monochrome mask
            self._status_item.button().setImage_(image)
        else:
            self._status_item.button().setTitle_("CX")
            
        # Create menu
        menu = NSMenu.alloc().init()
        
        # Quit item
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit ClipX", "terminate:", "q"
        )
        menu.addItem_(quit_item)
        
        self._status_item.setMenu_(menu)

    def _setup_key_monitor(self):
        """Set up key event monitors for popup navigation."""
        def handler(event):
            if self._popup_visible and self._popup:
                key_code = event.keyCode()
                print(f"[KeyMonitor] Key detected: {key_code}, popup_visible={self._popup_visible}", flush=True)
                
                # Arrow up
                if key_code == 126:
                    self._popup.move_selection(-1)
                    return None
                # Arrow down
                elif key_code == 125:
                    self._popup.move_selection(1)
                    return None
                # Enter
                elif key_code == 36:
                    self._popup.confirm_selection()
                    self._popup_visible = False
                    return None
                # Escape
                elif key_code == 53:
                    self._popup.hide()
                    self._popup_visible = False
                    return None
                # Any other key - dismiss the popup
                else:
                    print(f"[KeyMonitor] Dismissing popup on key {key_code}", flush=True)
                    self._popup.hide()
                    self._popup_visible = False
                    # Return event so the key still works (e.g., Cmd+Tab)
                    return event
            
            return event
        
        # Global handler for when popup loses focus (catches Cmd+Tab etc)
        def global_handler(event):
            if self._popup_visible and self._popup:
                key_code = event.keyCode()
                # Don't handle navigation keys in global handler
                if key_code not in [126, 125, 36, 53]:
                    print(f"[KeyMonitor] Global: Dismissing popup on key {key_code}", flush=True)
                    self._popup.hide()
                    self._popup_visible = False
        
        # Local monitor for when our app has focus
        NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, handler
        )
        
        # Global monitor for when other apps have focus
        NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, global_handler
        )
    
    def _on_clipboard_change(self, content: str):
        """Called when clipboard content changes."""
        preview = content[:50].replace('\n', ' ')
        if len(content) > 50:
            preview += '...'
        print(f"📋 Copied: {preview}")
    
    def _on_hotkey_trigger(self):
        """Called when Cmd+Option+V is pressed."""
        # This is called from a background thread - dispatch to main thread
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            'showPopupFromHotkey', None, False
        )
    
    def showPopupFromHotkey(self):
        """Show popup - called on main thread."""
        try:
            # Toggle popup - check actual visibility, not tracked state
            if self._popup.isVisible():
                print("[Main] Popup is visible, hiding...")
                self._popup.hide()
                return
            
            # Get clipboard history
            history = self._clipboard_monitor.get_history()
            if not history:
                print("📭 Clipboard history is empty")
                return
            
            # Store the focused element for later refocusing
            focused_element = self._accessibility.get_focused_element()
            self._popup.store_focused_element(focused_element)
            
            # Store the frontmost application so we can reactivate it before pasting
            from AppKit import NSWorkspace
            frontmost_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            self._popup.store_frontmost_app(frontmost_app)
            print(f"[Main] Stored frontmost app: {frontmost_app.localizedName() if frontmost_app else 'None'}", flush=True)
            
            # Get focused element position
            element_rect = self._accessibility.get_focused_element_rect()
            
            if element_rect:
                # Calculate position
                # Calculate position based on actual content height
                # num_items * ITEM_HEIGHT + (PADDING * 2)
                content_height = len(history) * ITEM_HEIGHT + (PADDING * 2)
                popup_height = min(content_height, POPUP_MAX_HEIGHT)
                
                x, y, show_above = calculate_popup_position(
                    element_rect, 
                    popup_height
                )
            else:
                # Fallback: center of screen
                from AppKit import NSScreen
                screen = NSScreen.mainScreen()
                if screen:
                    frame = screen.frame()
                    x = frame.size.width / 2
                    y = frame.size.height / 2
                else:
                    x, y = 500, 400
                show_above = False
            
            print(f"[Main] Showing popup at ({x}, {y}), above={show_above}")
            
            # Show popup
            self._popup.update_items(history)
            self._popup.show_at_position(x, y, show_above)
            self._popup.makeKeyAndOrderFront_(None)
            self._popup_visible = True
            
        except Exception as e:
            print(f"[Main] Error showing popup: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_item_selected(self, item):
        """Called when a clipboard item is selected."""
        self._popup_visible = False
        preview = item.content[:30].replace('\n', ' ')
        print(f"✅ Pasted: {preview}...")
    
    def applicationWillTerminate_(self, notification):
        """Cleanup on exit."""
        if self._clipboard_monitor:
            self._clipboard_monitor.stop()
        if self._hotkey_handler:
            self._hotkey_handler.stop()
        print("\nClipX stopped.")


def main():
    """Main entry point."""
    # Setup logging
    log_path = os.path.expanduser("~/clipx.log")
    sys.stdout = DebugLogger(log_path)
    sys.stderr = sys.stdout
    print(f"--- ClipX Starting at {log_path} ---", flush=True)

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, lambda s, f: NSApp.terminate_(None))
    
    # Create application
    app = NSApplication.sharedApplication()
    
    # Run as accessory (no dock icon)
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    
    # Set delegate
    delegate = ClipXDelegate.alloc().init()
    app.setDelegate_(delegate)
    
    # Run
    app.run()


if __name__ == "__main__":
    main()
