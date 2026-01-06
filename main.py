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
from ui import ClipboardPopup, calculate_popup_position, ITEM_HEIGHT, PADDING, POPUP_MAX_HEIGHT, EDIT_BUTTON_HEIGHT
from updater import Updater
import startup


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
        self._debug_mode = False  # Default to False
        self._has_accessibility_permission = False
        self._permission_check_timer = None
        
        return self
    
    @property
    def debug_mode(self):
        return self._debug_mode
    
    @debug_mode.setter
    def debug_mode(self, value):
        self._debug_mode = value
    
    def applicationDidFinishLaunching_(self, notification):
        """Called when app is ready."""
        print("ClipX starting...", flush=True)
        
        self._setup_status_item()
        
        # Check accessibility permission - this will show the system prompt
        self._accessibility = AccessibilityHelper()
        self._has_accessibility_permission = AccessibilityHelper.request_accessibility_permission()
        print(f"[Main] Accessibility permission: {self._has_accessibility_permission}", flush=True)
        
        # Check if we just updated (--updated flag passed by update script)
        just_updated = '--updated' in sys.argv
        if just_updated:
            print("[Main] Detected post-update relaunch", flush=True)
        
        if not self._has_accessibility_permission:
            print("\n⚠️  Accessibility permission required!")
            print("   The system should have prompted you to grant access.")
            print("   If not, go to: System Settings > Privacy & Security > Accessibility\n", flush=True)
            # Show an appropriate alert
            if just_updated:
                self._show_post_update_permission_alert()
            else:
                self._show_accessibility_required_alert()
        
        # Create popup
        print("[Main] Creating popup window...", flush=True)
        self._popup = ClipboardPopup.create(on_select=self._on_item_selected)
        self._popup._on_delete = self._on_item_delete
        print("[Main] Popup created.", flush=True)
        
        # Start clipboard monitor
        print("[Main] Starting clipboard monitor...", flush=True)
        # Start clipboard monitor
        print("[Main] Starting clipboard monitor...", flush=True)
        self._clipboard_monitor = ClipboardMonitor(
            on_change=self._on_clipboard_change,
            debug=self._debug_mode
        )
        self._clipboard_monitor.start()
        print("✓ Clipboard monitoring started", flush=True)
        
        # Start hotkey handler
        print("[Main] Starting hotkey handler...", flush=True)
        self._hotkey_handler = HotkeyHandler(
            on_trigger=self._on_hotkey_trigger,
            on_permission_denied=self._on_hotkey_permission_denied,
            debug=self._debug_mode
        )
        self._hotkey_handler.start()
        print("[Main] Hotkey handler started.", flush=True)
        
        # Add global key event monitor for when popup is visible
        self._setup_key_monitor()
        
        print("\n🚀 ClipX is running!")
        print("   • Copy text anywhere (Cmd+C) to add to history")
        print("   • Press Cmd+Option+V to show history popup")
        print("   • Press Ctrl+C in terminal to quit\n", flush=True)
        
        # Start periodic permission check if permission was denied
        if not self._has_accessibility_permission:
            self._start_permission_check_timer()
    
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
        
        # Helper to add icon
        def set_icon(item, name):
            image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
            if image:
                item.setImage_(image)
        
        # Clear History item
        clear_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Clear History", "clearHistory:", ""
        )
        set_icon(clear_item, "trash")
        menu.addItem_(clear_item)
        
        menu.addItem_(NSMenuItem.separatorItem())
        
        # Launch on startup item
        self._launch_at_startup_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Launch on startup", "toggleLaunchAtStartup:", ""
        )
        set_icon(self._launch_at_startup_item, "rocket")
        
        # Set initial state
        if startup.is_launch_at_startup():
            self._launch_at_startup_item.setState_(1)  # NSControlStateValueOn
        else:
            self._launch_at_startup_item.setState_(0)  # NSControlStateValueOff
        menu.addItem_(self._launch_at_startup_item)
        
        menu.addItem_(NSMenuItem.separatorItem())
        
        # Check for Updates item
        update_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Check for Updates...", "checkForUpdates:", ""
        )
        set_icon(update_item, "arrow.triangle.2.circlepath")
        menu.addItem_(update_item)
        
        # Quit item
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit ClipX", "terminate:", "q"
        )
        set_icon(quit_item, "power")
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
                    # Check if we should stay open (edit mode toggle or delete)
                    was_edit_mode = self._popup._is_edit_mode
                    was_on_edit_button = self._popup._selected_index == 0
                    self._popup.confirm_selection()
                    # Only close popup if we actually pasted (normal mode, item selected)
                    if not was_edit_mode and not was_on_edit_button:
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
    
    def _show_accessibility_required_alert(self):
        """Show an alert explaining that accessibility permission is required."""
        from AppKit import NSAlert, NSAlertStyleWarning
        
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Accessibility Permission Required")
        alert.setInformativeText_(
            "ClipX needs Accessibility access to detect the Cmd+Option+V hotkey.\n\n"
            "Without this permission, clipboard monitoring still works, but you won't be able to "
            "use the keyboard shortcut to open the clipboard history.\n\n"
            "Click 'Open Settings' to grant access, then enable ClipX in the list."
        )
        alert.setAlertStyle_(NSAlertStyleWarning)
        alert.addButtonWithTitle_("Open Settings")
        alert.addButtonWithTitle_("Later")
        
        response = alert.runModal()
        if response == 1000:  # Open Settings
            AccessibilityHelper.open_accessibility_settings()
    
    def _show_post_update_permission_alert(self):
        """Show alert after update explaining that permission needs to be re-granted."""
        from AppKit import NSAlert, NSAlertStyleWarning
        
        alert = NSAlert.alloc().init()
        alert.setMessageText_("ClipX Updated Successfully!")
        alert.setInformativeText_(
            "ClipX has been updated to the latest version.\n\n"
            "⚠️ macOS requires you to re-authorize accessibility access after updates. "
            "This is a macOS security feature.\n\n"
            "If you see an OLD ClipX entry in the list, it no longer works — "
            "macOS tracks each app version separately.\n\n"
            "Please click 'Open Settings' and:\n"
            "1. Remove the old ClipX entry (click −)\n"
            "2. Click + and add ClipX again\n"
            "3. Enable the new ClipX entry\n\n"
            "The hotkey (Cmd+Option+V) will start working automatically."
        )
        alert.setAlertStyle_(NSAlertStyleWarning)
        alert.addButtonWithTitle_("Open Settings")
        alert.addButtonWithTitle_("Later")
        
        response = alert.runModal()
        if response == 1000:  # Open Settings
            AccessibilityHelper.open_accessibility_settings()
    
    def _start_permission_check_timer(self):
        """Start a timer to periodically check if accessibility permission was granted."""
        from Foundation import NSTimer
        
        # Check every 3 seconds
        self._permission_check_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            3.0,
            self,
            'checkPermissionTimer:',
            None,
            True
        )
        print("[Main] Started permission check timer", flush=True)
    
    def checkPermissionTimer_(self, timer):
        """Timer callback to check if accessibility permission was granted."""
        has_permission = AccessibilityHelper.check_accessibility_permission()
        
        if has_permission and not self._has_accessibility_permission:
            print("[Main] ✓ Accessibility permission granted!", flush=True)
            self._has_accessibility_permission = True
            
            # Stop the timer
            if self._permission_check_timer:
                self._permission_check_timer.invalidate()
                self._permission_check_timer = None
            
            # Restart the hotkey handler now that we have permission
            if self._hotkey_handler:
                self._hotkey_handler.stop()
                self._hotkey_handler = HotkeyHandler(
                    on_trigger=self._on_hotkey_trigger,
                    on_permission_denied=self._on_hotkey_permission_denied,
                    debug=self._debug_mode
                )
                self._hotkey_handler.start()
                print("[Main] Hotkey handler restarted with new permission", flush=True)
    
    def _on_hotkey_permission_denied(self):
        """Called from HotkeyHandler when CGEventTap creation fails."""
        print("[Main] Hotkey handler reported permission denied", flush=True)
        # Start the permission check timer if not already running
        if not self._permission_check_timer:
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                '_start_permission_check_timer', None, False
            )

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
                # Matching ui/popup.py logic:
                # items_height + edit_button_space + (PADDING * 3)
                edit_button_space = EDIT_BUTTON_HEIGHT + PADDING
                items_height = len(history) * ITEM_HEIGHT
                content_height = items_height + edit_button_space + (PADDING * 3)
                
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
    
    def _on_item_delete(self, index: int):
        """Called when a clipboard item is deleted via edit mode."""
        print(f"[Main] _on_item_delete ENTER index={index}", flush=True)
        try:
            if self._clipboard_monitor:
                print(f"[Main] Calling delete_item...", flush=True)
                result = self._clipboard_monitor.delete_item(index)
                print(f"[Main] delete_item returned: {result}", flush=True)
            print(f"[Main] _on_item_delete EXIT", flush=True)
        except Exception as e:
            print(f"[Main] Error in _on_item_delete: {e}", flush=True)
            import traceback
            traceback.print_exc()
    
    def clearHistory_(self, sender):
        """Clear clipboard history."""
        print("[Main] Clearing history...")
        if self._clipboard_monitor:
            self._clipboard_monitor.clear_history()
            
            # If popup is visible, update it or close it
            if self._popup_visible and self._popup:
                self._popup.hide()
                self._popup_visible = False
                print("[Main] Popup hidden after clearing history")

    def toggleLaunchAtStartup_(self, sender):
        """Toggle launch at startup."""
        current_state = sender.state()
        new_state = not current_state
        
        if startup.toggle_launch_at_startup(new_state):
            sender.setState_(1 if new_state else 0)
            print(f"[Main] Launch at startup set to: {new_state}")
        else:
            print("[Main] Failed to toggle launch at startup")

    def checkForUpdates_(self, sender):
        """Check for updates."""
        print("[Main] User requested update check...")
        
        # Run in background to avoid blocking UI? 
        # For simplicity in this iteration, we'll run sync (might block briefly)
        # or use a simple timer/thread if needed. Since urllib is blocking, 
        # let's just do it. Ideally dispatch_async.
        
        release_info = Updater.check_for_updates()
        if Updater.show_update_dialog(release_info):
            if release_info:
                # If install_and_restart returns True, it means the update script is running
                # and we should terminate to allow it to replace the app file.
                if Updater.install_and_restart(release_info.get('download_url')):
                    print("[Main] Update script started. Terminating...")
                    from AppKit import NSApp
                    NSApp.terminate_(self)

    def applicationWillTerminate_(self, notification):
        """Cleanup on exit."""
        if self._clipboard_monitor:
            self._clipboard_monitor.stop()
        if self._hotkey_handler:
            self._hotkey_handler.stop()
        print("\nClipX stopped.")


def main():
    """Main entry point."""
    # Detect if we are running as a packaged app
    is_packaged = getattr(sys, 'frozen', False)
    debug_mode = not is_packaged

    if debug_mode:
        # Setup specific logging only in dev
        log_path = os.path.expanduser("~/clipx.log")
        sys.stdout = DebugLogger(log_path)
        sys.stderr = sys.stdout
        print(f"--- ClipX Starting (Dev Mode) at {log_path} ---", flush=True)
    else:
        # In production, we don't redirect stdout/stderr to a file
        # We can also silence print statements if desired, but just not writing to disk is the main goal
        pass

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, lambda s, f: NSApp.terminate_(None))
    
    # Create application
    app = NSApplication.sharedApplication()
    
    # Check for another running instance
    from AppKit import NSRunningApplication, NSAlert, NSAlertStyleCritical
    
    current_pid = os.getpid()
    bundle_id = "com.clipx.app" # Must match setup.py
    
    running_apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
    other_instances = [a for a in running_apps if a.processIdentifier() != current_pid]
    
    if other_instances:
        print(f"[Main] Found {len(other_instances)} other instance(s) running.")
        
        # We need to activate the app to show the alert, even if it's an agent
        app.setActivationPolicy_(1) # NSApplicationActivationPolicyRegular for alert
        
        alert = NSAlert.alloc().init()
        alert.setMessageText_("ClipX is already running")
        alert.setInformativeText_("Another instance of ClipX is already running. What would you like to do?")
        alert.setAlertStyle_(NSAlertStyleCritical)
        alert.addButtonWithTitle_("Quit New Instance")
        alert.addButtonWithTitle_("Terminate Other & Continue")
        
        # Bring to front
        app.activateIgnoringOtherApps_(True)
        
        response = alert.runModal()
        
        if response == 1000: # Quit New Instance
            print("[Main] User chose to quit new instance.")
            sys.exit(0)
        elif response == 1001: # Terminate Other
            print("[Main] User chose to terminate other instance(s).")
            for other_app in other_instances:
                other_app.forceTerminate()
                # Wait briefly for it to die?
            # Continue starting up...
            pass

    
    # Run as accessory (no dock icon)
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    
    # Set delegate
    delegate = ClipXDelegate.alloc().init()
    delegate.debug_mode = debug_mode
    app.setDelegate_(delegate)
    
    # Run
    app.run()


if __name__ == "__main__":
    main()
