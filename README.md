# ClipX

The most simple clipboard history manager for macOS

![macOS](https://img.shields.io/badge/macOS-13.0+-blue)
![Python](https://img.shields.io/badge/Python-3.10+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Clipboard History** — Automatically tracks your last 50 copied items (text and images)
- **Global Hotkey** — Press `Cmd + Option + V` anywhere to open the popup
- **Smart Positioning** — Popup appears near your current text cursor using Accessibility APIs
- **Image Support** — Copies images with thumbnail previews (PNG/TIFF)
- **Deduplication** — Automatically removes duplicate text entries
- **Native UI** — Glassmorphism design with smooth spring animations
- **Lightweight** — Runs as a menu bar app with no dock icon

## Usage

### Shortcut

Press **Cmd + Option + V** to open the clipboard history popup.

### Popup Location

The popup attempts to appear intelligently based on your context:
- Often directly below your text cursor
- Near the active input field (e.g., Chrome URL bar)

### Navigation

| Action | Shortcut |
|--------|----------|
| Show clipboard history | `Cmd + Option + V` |
| Navigate items | `Up` / `Down` arrows |
| Paste selected item | `Enter` or click |
| Dismiss popup | `Escape` or click outside |
| Quit app | Click menu bar icon → Quit |

### Closing the Popup

The popup can be dismissed by:
- Pressing the **Esc** key
- Clicking anywhere outside the popup window
- Selecting an item to paste (this will paste the item and close the popup)

## Installation

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

1. Open **System Settings > Privacy & Security > Accessibility**
2. Add your Terminal or IDE to the list
3. Enable the toggle

## Architecture

```
ClipX/
├── main.py              # App entry point & coordinator
├── clipboard_monitor.py # Polls NSPasteboard for changes
├── hotkey_handler.py    # CGEventTap for global hotkey
├── accessibility.py     # AX API for cursor position
├── popup_window.py      # NSPanel with blur effect
└── icon.icns            # Menu bar icon
```

## License

MIT License — feel free to use and modify.

---

Made with care for macOS power users
