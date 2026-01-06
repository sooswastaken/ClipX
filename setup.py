"""
Script for building the ClipX macOS application.

Usage:
    python3 setup.py py2app
"""

from setuptools import setup

APP = ['main.py']
DATA_FILES = ['icon.icns']
OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'icon.icns',
    'plist': {
        'LSUIElement': True,  # Agent app (no dock icon, lives in menu bar)
        'CFBundleName': 'ClipX',
        'CFBundleDisplayName': 'ClipX',
        'CFBundleIdentifier': 'com.clipx.app',
        'CFBundleVersion': '0.1.0',
        'CFBundleShortVersionString': '0.1.0',
        'NSHumanReadableCopyright': 'Copyright © 2026',
    },
    'packages': ['objc', 'AppKit', 'Foundation', 'Quartz', 'ApplicationServices'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
