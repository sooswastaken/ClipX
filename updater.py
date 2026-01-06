import json
import urllib.request
import urllib.error
import os
import tempfile
import zipfile
import shutil
import subprocess
from pathlib import Path
from AppKit import NSAlert, NSAlertStyleInformational, NSAlertStyleCritical

import re

RELEASE_URL = "https://api.github.com/repos/sooswastaken/ClipX/releases/tags/latest"

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
                    # Look for "Commit: <sha>"
                    remote_sha = None
                    if release_info.get('body'):
                        match = re.search(r'Commit: ([a-f0-9]+)', release_info['body'])
                        if match:
                            remote_sha = match.group(1)
                            release_info["remote_sha"] = remote_sha
                    
                    # Compare versions
                    if local_sha and remote_sha:
                        # Simple prefix matching (GH usually gives short SHA or long SHA)
                        # Normalize to verify equality
                        if remote_sha.startswith(local_sha) or local_sha.startswith(remote_sha):
                            release_info["status"] = "UP_TO_DATE"
                        else:
                            release_info["status"] = "UPDATE_AVAILABLE"
                            # Fetch changelog
                            commits = Updater.get_compare_data(local_sha, remote_sha)
                            # Extract clean messages (first line)
                            release_info["changelog"] = [c['commit']['message'].split('\n')[0] for c in commits]
                            
                    elif not local_sha:
                        # No local version info (dev mode or old build), assume update available ??
                        # Or maybe UNKNOWN. Let's say UNKNOWN but available to download.
                        print("[Updater] No local version info found.")
                        release_info["status"] = "UNKNOWN"
                    
                    return release_info
        except Exception as e:
            print(f"[Updater] Error checking for updates: {e}")
            return None
        return None

    @staticmethod
    def download_and_install(download_url):
        # ... existing download code ...
        # (Note: keeping existing methods, just overwriting check_for_updates upwards)
        pass 

    # We need to preserve the other methods we aren't changing, but since replace_file_content 
    # replaces the block, I'll need to be careful. 
    # Actually, the previous tool call covered check_for_updates. 
    # I should target check_for_updates specifically, and show_update_dialog specifically.
    pass

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
                    changelog_text = "\n\nChanges:\n"
                    # Show last 10 commits
                    for msg in reversed(changelog[-10:]):
                         changelog_text += f"- {msg}\n"
                    if len(changelog) > 10:
                        changelog_text = f"\n\nChanges (last 10 of {len(changelog)}):\n" + "\n".join([f"- {msg}" for msg in reversed(changelog[-10:])]) + "\n..."
                
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
    def install_and_restart(download_url):
        """
        Download, extract, and replace the running application.
        """
        try:
            print(f"[Updater] Downloading update from {download_url}...")
            
            # Create temp directory
            temp_dir = Path(tempfile.mkdtemp(prefix="ClipX_Update_"))
            zip_path = temp_dir / "ClipX.zip"
            
            # Download
            with urllib.request.urlopen(download_url) as response, open(zip_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
            
            # Extract
            print("[Updater] Extracting...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            new_app_path = temp_dir / "ClipX.app"
            if not new_app_path.exists():
                print("[Updater] Error: ClipX.app not found in zip")
                return False

            # FIX: Restore executable permissions
            # ZipFile extractall doesn't always preserve permissions
            executable_path = new_app_path / "Contents" / "MacOS" / "ClipX"
            if executable_path.exists():
                print(f"[Updater] Restoring executable permissions for {executable_path}")
                os.chmod(executable_path, 0o755)
            else:
                 print(f"[Updater] Warning: Executable not found at {executable_path}")

            # Detect current app path
            from AppKit import NSBundle
            current_bundle_path = NSBundle.mainBundle().bundlePath()
            
            # Check if we are running as a packaged app
            # CRITICAL: Only use sys.frozen to detect packaged app. 
            # Checking .endswith('.app') is DANGEROUS because when running from source,
            # the main bundle is often the Python interpreter itself (Python.app).
            is_packaged = getattr(os.sys, 'frozen', False)
            
            if is_packaged and current_bundle_path != str(new_app_path):
                print(f"[Updater] Preparing to replace {current_bundle_path}...")
                
                # Create and run update script
                script_path = Updater._create_install_script(
                    current_bundle_path, 
                    str(new_app_path), 
                    os.getpid()
                )
                
                print(f"[Updater] Launching update script: {script_path}")
                subprocess.Popen(['/bin/bash', script_path], start_new_session=True)
                
                # Signal success (caller should exit)
                return True
            else:
                print("[Updater] Not running as packaged app (or path mismatch), revealing in Finder instead.")
                subprocess.run(["open", "-R", str(new_app_path)])
                return False
            
        except Exception as e:
            print(f"[Updater] Error installing update: {e}")
            return False

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
                    # Show last 10 commits
                    commits_to_show = changelog[-10:]
                    # Reverse so newest is top
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
