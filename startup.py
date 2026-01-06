import sys
import os
import subprocess

def get_app_path():
    """
    Get the path to the application.
    If frozen (packaged), returns the .app path.
    If script, returns the python script path.
    """
    if getattr(sys, 'frozen', False):
        # We are running in a bundle
        # sys.executable points to the binary inside Contents/MacOS
        # We want the .app bundle path, which is 3 levels up
        return os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
    else:
        # We are running as a script
        # For development testing, we can add the python script itself if needed,
        # but realistically, "Launch on startup" is for the packaged app.
        # However, for testing logic, we can return the current script path 
        # or a dummy value. Let's return the abspath of main.py
        # Assuming this file is next to main.py
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))

def is_launch_at_startup():
    """Check if the app is in the Login Items."""
    app_path = get_app_path()
    
    # AppleScript to check if any login item has the specific path
    script = f'''
    tell application "System Events"
        set itemPaths to path of every login item
        if "{app_path}" is into itemPaths then
            return true
        else
            return false
        end if
    end tell
    '''
    # Note: "is into" might not be valid AppleScript for list containment check depending on version.
    # Better:
    script = f'''
    tell application "System Events"
        repeat with item_ in every login item
            try
                if path of item_ is "{app_path}" then
                    return true
                end if
            end try
        end repeat
        return false
    end tell
    '''
    
    try:
        result = subprocess.check_output(['osascript', '-e', script], text=True).strip()
        return result == 'true'
    except subprocess.CalledProcessError:
        print("[Startup] Failed to check login items")
        return False

def toggle_launch_at_startup(enable):
    """Add or remove the app from Login Items."""
    app_path = get_app_path()
    app_name = os.path.split(app_path)[1]
    # For .app, remove extension for the name we typically want to see
    if app_name.endswith('.app'):
        app_name = os.path.splitext(app_name)[0]
    
    if enable:
        if is_launch_at_startup():
            print(f"[Startup] App already in login items.")
            return True
            
        print(f"[Startup] Adding '{app_name}' at '{app_path}' to Login Items")
        script = f'''
        tell application "System Events"
            make new login item at end with properties {{path:"{app_path}", hidden:false, name:"{app_name}"}}
        end tell
        '''
    else:
        print(f"[Startup] Removing '{app_path}' from Login Items")
        script = f'''
        tell application "System Events"
            set loginItems to every login item
            repeat with item_ in loginItems
                try
                    if path of item_ is "{app_path}" then
                        delete item_
                    end if
                end try
            end repeat
        end tell
        '''
        
    try:
        subprocess.check_call(['osascript', '-e', script])
        return True
    except subprocess.CalledProcessError as e:
        print(f"[Startup] Failed to toggle login item: {e}")
        return False
