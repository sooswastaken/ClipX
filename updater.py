import json
import urllib.request
import urllib.error
import os
import tempfile
import zipfile
import shutil
import subprocess
import threading
from pathlib import Path
from AppKit import (
    NSAlert, NSAlertStyleInformational, NSAlertStyleCritical,
    NSPanel, NSView, NSTextField, NSColor, NSFont,
    NSMakeRect, NSMakePoint, NSApplication,
    NSScreenSaverWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSVisualEffectView,
)
from Foundation import NSTimer

import re

RELEASE_URL = "https://api.github.com/repos/sooswastaken/ClipX/releases/tags/latest"


class UpdateProgressWindow:
    """A small floating progress window shown during update download/install."""
    
    _instance = None
    
    @classmethod
    def show(cls):
        """Create and show the progress window. Returns the instance."""
        if cls._instance:
            cls._instance.close()
        
        inst = cls()
        cls._instance = inst
        return inst
    
    def __init__(self):
        width = 300
        height = 100
        
        # Center on screen
        from AppKit import NSScreen
        screen = NSScreen.mainScreen()
        if screen:
            sf = screen.frame()
            x = (sf.size.width - width) / 2
            y = (sf.size.height - height) / 2
        else:
            x, y = 400, 400
        
        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            0,  # Borderless
            2,  # NSBackingStoreBuffered
            False
        )
        self._panel.setLevel_(NSScreenSaverWindowLevel)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setOpaque_(False)
        self._panel.setHasShadow_(True)
        self._panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces |
            NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        
        content = self._panel.contentView()
        
        # Blur background
        blur = NSVisualEffectView.alloc().initWithFrame_(content.bounds())
        blur.setMaterial_(13)  # hudWindow
        blur.setBlendingMode_(0)  # behindWindow
        blur.setState_(1)  # active
        blur.setWantsLayer_(True)
        blur.layer().setCornerRadius_(12)
        blur.layer().setMasksToBounds_(True)
        blur.setAutoresizingMask_(18)
        content.addSubview_(blur)
        
        # Title
        title = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 58, width - 40, 24))
        title.setStringValue_("Updating ClipX...")
        title.setBezeled_(False)
        title.setDrawsBackground_(False)
        title.setEditable_(False)
        title.setSelectable_(False)
        title.setTextColor_(NSColor.whiteColor())
        title.setFont_(NSFont.boldSystemFontOfSize_(14))
        blur.addSubview_(title)
        
        # Progress bar
        from AppKit import NSProgressIndicator
        self._progress = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(20, 38, width - 40, 12)
        )
        self._progress.setStyle_(0)  # NSProgressIndicatorStyleBar
        self._progress.setIndeterminate_(False)
        self._progress.setMinValue_(0)
        self._progress.setMaxValue_(100)
        self._progress.setDoubleValue_(0)
        self._progress.setWantsLayer_(True)
        blur.addSubview_(self._progress)
        
        # Status label
        self._status = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 14, width - 40, 18))
        self._status.setStringValue_("Downloading...")
        self._status.setBezeled_(False)
        self._status.setDrawsBackground_(False)
        self._status.setEditable_(False)
        self._status.setSelectable_(False)
        self._status.setTextColor_(NSColor.colorWithWhite_alpha_(0.7, 1.0))
        self._status.setFont_(NSFont.systemFontOfSize_(11))
        blur.addSubview_(self._status)
        
        # Show
        app = NSApplication.sharedApplication()
        app.activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)
        self._panel.orderFrontRegardless()
    
    def set_status(self, text):
        """Update the status label (must be called on main thread)."""
        self._status.setStringValue_(text)
    
    def set_progress(self, value):
        """Update progress bar value 0-100 (must be called on main thread)."""
        self._progress.setDoubleValue_(value)
    
    def set_indeterminate(self, value):
        """Switch between determinate and indeterminate mode."""
        self._progress.setIndeterminate_(value)
        if value:
            self._progress.startAnimation_(None)
        else:
            self._progress.stopAnimation_(None)
    
    def close(self):
        """Close and destroy the progress window."""
        self._panel.orderOut_(None)
        UpdateProgressWindow._instance = None


class Updater:
    @staticmethod
    def get_local_version():
        """
        Read the local version_info.json file.
        Returns a dict with commit_sha and build_time, or None if not found.
        """
        try:
            # Try to find the file in the Resources directory (packaged app)
            from AppKit import NSBundle
            path = NSBundle.mainBundle().pathForResource_ofType_("version_info", "json")
            
            if not path:
                # Fallback to current directory (dev mode)
                path = "version_info.json"
            
            if os.path.exists(path):
                with open(path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[Updater] Error reading local version: {e}")
            return None
        return None

    @staticmethod
    def get_compare_data(local_sha, remote_sha):
        """
        Fetch the list of commits between local_sha and remote_sha.
        """
        try:
            url = f"https://api.github.com/repos/sooswastaken/ClipX/compare/{local_sha}...{remote_sha}"
            print(f"[Updater] Fetching changelog from {url}...")
            with urllib.request.urlopen(url, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    return data.get("commits", [])
        except Exception as e:
            print(f"[Updater] Error fetching changelog: {e}")
            return []
        return []

    @staticmethod
    def check_for_updates():
        """
        Check GitHub for the latest release.
        Returns a dictionary with release info or None if failed.
        """
        try:
            print(f"[Updater] Checking for updates from {RELEASE_URL}...")
            
            local_version = Updater.get_local_version()
            local_sha = local_version.get('commit_sha') if local_version else None
            
            with urllib.request.urlopen(RELEASE_URL, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    
                    # Extract relevant info
                    release_info = {
                        "tag_name": data.get("tag_name"),
                        "published_at": data.get("published_at"),
                        "body": data.get("body"),
                        "html_url": data.get("html_url"),
                        "assets": data.get("assets", []),
                        "status": "UNKNOWN",
                        "changelog": []
                    }
                    
                    # Find the asset download URL
                    for asset in release_info["assets"]:
                        if asset["name"] == "ClipX.zip":
                            release_info["download_url"] = asset["browser_download_url"]
                            break
                    
                    # Try to parse SHA from release body
                    remote_sha = None
                    if release_info.get('body'):
                        match = re.search(r'Commit: ([a-f0-9]+)', release_info['body'])
                        if match:
                            remote_sha = match.group(1)
                            release_info["remote_sha"] = remote_sha
                    
                    # Compare versions
                    if local_sha and remote_sha:
                        if remote_sha.startswith(local_sha) or local_sha.startswith(remote_sha):
                            release_info["status"] = "UP_TO_DATE"
                        else:
                            release_info["status"] = "UPDATE_AVAILABLE"
                            commits = Updater.get_compare_data(local_sha, remote_sha)
                            release_info["changelog"] = [c['commit']['message'].split('\n')[0] for c in commits]
                            
                    elif not local_sha:
                        print("[Updater] No local version info found.")
                        release_info["status"] = "UNKNOWN"
                    
                    return release_info
        except Exception as e:
            print(f"[Updater] Error checking for updates: {e}")
            return None
        return None

    @staticmethod
    def show_update_dialog(release_info):
        """
        Show a dialog to the user about the update.
        Returns True if user wants to update, False otherwise.
        """
        alert = NSAlert.alloc().init()
        
        if release_info:
            status = release_info.get("status", "UNKNOWN")
            tag_name = release_info.get('tag_name')
            published_date = release_info.get('published_at', 'Unknown date').split('T')[0]
            
            if status == "UP_TO_DATE":
                alert.setMessageText_("You are up to date")
                alert.setInformativeText_(
                    f"ClipX {tag_name} is currently the newest version available.\n\n"
                    f"Installed Commit: {Updater.get_local_version().get('commit_sha')[:7]}\n"
                    f"Latest Commit: {release_info.get('remote_sha')[:7]}"
                )
                alert.addButtonWithTitle_("OK")
                alert.runModal()
                return False
                
            elif status == "UPDATE_AVAILABLE":
                alert.setMessageText_("Update Available")
                
                changelog_text = ""
                changelog = release_info.get("changelog", [])
                if changelog:
                    commits_to_show = changelog[-10:]
                    commits_to_show.reverse()
                    
                    changelog_text = "\n\nChanges:\n" + "\n".join([f"- {msg}" for msg in commits_to_show])
                    
                    if len(changelog) > 10:
                        changelog_text += f"\n... and {len(changelog) - 10} more commits."
                        
                info_text = (
                    f"A new version of ClipX is available!\n\n"
                    f"Release: {tag_name} ({published_date})\n"
                    f"{changelog_text}\n\n"
                    "Would you like to download and install this update?"
                )
                alert.setInformativeText_(info_text)
                alert.addButtonWithTitle_("Download & Update")
                alert.addButtonWithTitle_("Cancel")
                response = alert.runModal()
                return response == 1000
                
            else:
                # UNKNOWN or fallback
                alert.setMessageText_("Check for Updates")
                info_text = (
                    f"Latest Release: {tag_name}\n"
                    f"Published: {published_date}\n\n"
                    f"Release Notes:\n{release_info.get('body')}\n\n"
                    "Would you like to download this update?"
                )
                alert.setInformativeText_(info_text)
                alert.addButtonWithTitle_("Download & Update")
                alert.addButtonWithTitle_("Cancel")
                response = alert.runModal()
                return response == 1000

        else:
            alert.setMessageText_("Update Check Failed")
            alert.setInformativeText_("Could not verify release information. Please check your internet connection.")
            alert.setAlertStyle_(NSAlertStyleCritical)
            alert.addButtonWithTitle_("OK")
            
            alert.runModal()
            return False

    @staticmethod
    def _create_install_script(old_app_path, new_app_path, pid):
        """
        Create a shell script to swap the apps and restart.
        """
        script_content = f"""#!/bin/bash
# Wait for the old app to terminate
while kill -0 {pid} 2>/dev/null; do
    sleep 0.5
done

# Short delay to ensure file locks are released
sleep 1

# Move new app to old app location
echo "Replacing {old_app_path} with {new_app_path}"
rm -rf "{old_app_path}"
mv "{new_app_path}" "{old_app_path}"

# Relaunch with --updated flag so app knows it was just updated
echo "Relaunching..."
open "{old_app_path}" --args --updated

# Cleanup script
rm -- "$0"
"""
        script_path = os.path.join(tempfile.gettempdir(), f"clipx_update_{pid}.sh")
        with open(script_path, 'w') as f:
            f.write(script_content)
        
        os.chmod(script_path, 0o755)
        return script_path

    @staticmethod
    def install_and_restart_async(download_url, on_complete=None):
        """
        Download, extract, and replace the running application with progress UI.
        Runs the download on a background thread, updates progress on main thread.
        on_complete(success: bool) is called on the main thread when done.
        """
        progress = UpdateProgressWindow.show()
        
        def _update_status(text):
            from PyObjCTools import AppHelper
            AppHelper.callAfter(progress.set_status, text)
        
        def _update_progress(value):
            from PyObjCTools import AppHelper
            AppHelper.callAfter(progress.set_progress, value)
        
        def _set_indeterminate(value):
            from PyObjCTools import AppHelper
            AppHelper.callAfter(progress.set_indeterminate, value)
        
        def _finish(success):
            from PyObjCTools import AppHelper
            def _do_finish():
                progress.close()
                if on_complete:
                    on_complete(success)
            AppHelper.callAfter(_do_finish)
        
        def _download_thread():
            try:
                print(f"[Updater] Downloading update from {download_url}...")
                _update_status("Downloading update...")
                
                # Create temp directory
                temp_dir = Path(tempfile.mkdtemp(prefix="ClipX_Update_"))
                zip_path = temp_dir / "ClipX.zip"
                
                # Download with progress
                req = urllib.request.urlopen(download_url)
                total_size = int(req.headers.get('Content-Length', 0))
                downloaded = 0
                block_size = 8192
                
                with open(zip_path, 'wb') as out_file:
                    while True:
                        chunk = req.read(block_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = (downloaded / total_size) * 70  # 0-70% for download
                            _update_progress(pct)
                
                req.close()
                
                # Extract
                _update_status("Extracting...")
                _update_progress(75)
                print("[Updater] Extracting...")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                _update_progress(85)
                
                new_app_path = temp_dir / "ClipX.app"
                if not new_app_path.exists():
                    print("[Updater] Error: ClipX.app not found in zip")
                    _update_status("Error: app not found in archive")
                    _finish(False)
                    return

                # Restore executable permissions
                executable_path = new_app_path / "Contents" / "MacOS" / "ClipX"
                if executable_path.exists():
                    os.chmod(executable_path, 0o755)

                _update_status("Installing...")
                _update_progress(90)

                # Detect current app path
                from AppKit import NSBundle
                current_bundle_path = NSBundle.mainBundle().bundlePath()
                is_packaged = getattr(os.sys, 'frozen', False)
                
                if is_packaged and current_bundle_path != str(new_app_path):
                    print(f"[Updater] Preparing to replace {current_bundle_path}...")
                    
                    script_path = Updater._create_install_script(
                        current_bundle_path, 
                        str(new_app_path), 
                        os.getpid()
                    )
                    
                    _update_progress(100)
                    _update_status("Restarting...")
                    
                    print(f"[Updater] Launching update script: {script_path}")
                    subprocess.Popen(['/bin/bash', script_path], start_new_session=True)
                    
                    _finish(True)
                else:
                    print("[Updater] Not running as packaged app, revealing in Finder instead.")
                    _update_progress(100)
                    _update_status("Done! Opening in Finder...")
                    subprocess.run(["open", "-R", str(new_app_path)])
                    _finish(False)
                
            except Exception as e:
                print(f"[Updater] Error installing update: {e}")
                import traceback
                traceback.print_exc()
                _update_status(f"Error: {e}")
                _finish(False)
        
        # Start background thread
        thread = threading.Thread(target=_download_thread, daemon=True)
        thread.start()
