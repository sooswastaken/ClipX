# ClipX

A native clipboard history manager for macOS — bringing Windows' `Win + V` clipboard experience to your Mac.

![macOS](https://img.shields.io/badge/macOS-13.0+-blue)
![Python](https://img.shields.io/badge/Python-3.10+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Features

- **📋 Clipboard History** — Automatically tracks your last 50 copied items (text and images)
- **⌨️ Global Hotkey** — Press `⌘ ⌥ V` (Cmd+Option+V) anywhere to open the popup
- **🎯 Smart Positioning** — Popup appears near your current text cursor using Accessibility APIs
- **🖼️ Image Support** — Copies images with thumbnail previews (PNG/TIFF)
- **🔍 Deduplication** — Automatically removes duplicate text entries
- **🎨 Native UI** — Glassmorphism design with smooth spring animations
- **⚡ Lightweight** — Runs as a menu bar app with no dock icon

## 📦 Installation

### Prerequisites

- macOS 13.0 (Ventura) or later
- Python 3.10+

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/ClipX.git
cd ClipX

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py
```

### Grant Accessibility Permission

ClipX requires Accessibility permission to:
- Detect the global hotkey
- Position the popup near your cursor

1. Open **System Settings → Privacy & Security → Accessibility**
2. Add your Terminal or IDE to the list
3. Enable the toggle

## 🚀 Usage

| Action | Shortcut |
|--------|----------|
| Show clipboard history | `⌘ ⌥ V` |
| Navigate items | `↑` `↓` |
| Paste selected item | `Enter` or click |
| Dismiss popup | `Escape` or click outside |
| Quit app | Click menu bar icon → Quit |

## 🏗️ Architecture

```
ClipX/
├── main.py              # App entry point & coordinator
├── clipboard_monitor.py # Polls NSPasteboard for changes
├── hotkey_handler.py    # CGEventTap for global hotkey
├── accessibility.py     # AX API for cursor position
├── popup_window.py      # NSPanel with blur effect
└── icon.icns            # Menu bar icon
```

## 🛠️ Building as a Standalone App

```bash
python setup.py py2app
```

The `.app` bundle will be created in the `dist/` folder.

## 📝 License

MIT License — feel free to use and modify.

---

Made with ❤️ for macOS power users
