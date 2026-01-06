"""Clipboard Monitor - Polls NSPasteboard for changes and maintains history.
Supports text and image content with persistent storage.
"""

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime

from AppKit import (
    NSPasteboard, 
    NSPasteboardTypeString,
    NSPasteboardTypePNG,
    NSPasteboardTypeTIFF,
    NSImage,
    NSBitmapImageRep,
    NSPNGFileType,
    NSMakeSize,
    NSMakeRect,
    NSCompositingOperationCopy,
    NSGraphicsContext,
)


@dataclass
class ClipboardItem:
    """A single clipboard history item supporting text and images."""
    content_type: str  # "text", "image", or "mixed"
    timestamp: datetime
    text_content: Optional[str] = None
    image_data: Optional[bytes] = None  # PNG data for storage
    thumbnail: Optional[object] = field(default=None, repr=False)  # NSImage, excluded from repr
    
    @property
    def preview(self) -> str:
        """Get a truncated preview for display."""
        if self.content_type == "image":
            return "Image"
        elif self.text_content:
            text = self.text_content.replace('\n', ' ').strip()
            if len(text) > 200:
                return text[:197] + '...'
            return text
        return "Empty"
    
    @property
    def content(self) -> str:
        """Backwards compatibility - return text content."""
        return self.text_content or ""
    
    def has_image(self) -> bool:
        return self.image_data is not None


def create_thumbnail(image: 'NSImage', size: int = 32) -> 'NSImage':
    """Create a square thumbnail from an NSImage."""
    try:
        # Get original size
        orig_size = image.size()
        
        # Calculate scale to fill the square (crop to fit)
        scale = max(size / orig_size.width, size / orig_size.height)
        new_width = orig_size.width * scale
        new_height = orig_size.height * scale
        
        # Create new image
        thumbnail = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
        thumbnail.lockFocus()
        
        # Draw scaled and centered
        x_offset = (size - new_width) / 2
        y_offset = (size - new_height) / 2
        
        image.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(x_offset, y_offset, new_width, new_height),
            NSMakeRect(0, 0, orig_size.width, orig_size.height),
            NSCompositingOperationCopy,
            1.0
        )
        
        thumbnail.unlockFocus()
        return thumbnail
    except Exception as e:
        print(f"[ClipboardMonitor] Error creating thumbnail: {e}")
        return None


def image_to_png_data(image: 'NSImage') -> Optional[bytes]:
    """Convert NSImage to PNG bytes."""
    try:
        tiff_data = image.TIFFRepresentation()
        if not tiff_data:
            return None
        bitmap = NSBitmapImageRep.imageRepWithData_(tiff_data)
        if not bitmap:
            return None
        png_data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
        return bytes(png_data) if png_data else None
    except Exception as e:
        print(f"[ClipboardMonitor] Error converting image to PNG: {e}")
        return None


class ClipboardMonitor:
    """
    Monitors the system clipboard for changes.
    Uses polling since NSPasteboard doesn't provide change notifications.
    Supports text and image content.
    """
    
    # Path for persistent storage
    STORAGE_DIR = Path.home() / "Library" / "Application Support" / "ClipX"
    HISTORY_FILE = STORAGE_DIR / "history.json"
    
    def __init__(self, on_change: Optional[Callable[[str], None]] = None, max_history: int = 50, debug: bool = False):
        self.on_change = on_change
        self.max_history = max_history
        self.debug = debug
        self.history: List[ClipboardItem] = []
        
        self._pasteboard = NSPasteboard.generalPasteboard()
        self._last_change_count = self._pasteboard.changeCount()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Load persisted history
        self._load_history()
    
    def start(self):
        """Start monitoring clipboard in background thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop monitoring clipboard and save history."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._save_history()
    
    def _load_history(self):
        """Load history from disk."""
        try:
            if not self.HISTORY_FILE.exists():
                print("[ClipboardMonitor] No history file found, starting fresh")
                return
            
            with open(self.HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for item_data in data:
                # Decode image data if present
                image_data = None
                thumbnail = None
                if item_data.get('image_data'):
                    image_data = base64.b64decode(item_data['image_data'])
                    # Recreate thumbnail from image data
                    from AppKit import NSImage, NSData
                    ns_data = NSData.dataWithBytes_length_(image_data, len(image_data))
                    image = NSImage.alloc().initWithData_(ns_data)
                    if image:
                        thumbnail = create_thumbnail(image, 32)
                
                item = ClipboardItem(
                    content_type=item_data['content_type'],
                    timestamp=datetime.fromisoformat(item_data['timestamp']),
                    text_content=item_data.get('text_content'),
                    image_data=image_data,
                    thumbnail=thumbnail
                )
                self.history.append(item)
            
            print(f"[ClipboardMonitor] Loaded {len(self.history)} items from history")
        except Exception as e:
            print(f"[ClipboardMonitor] Error loading history: {e}")
    
    def _save_history(self):
        """Save history to disk."""
        try:
            # Ensure directory exists
            self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            
            data = []
            with self._lock:
                for item in self.history:
                    item_data = {
                        'content_type': item.content_type,
                        'timestamp': item.timestamp.isoformat(),
                        'text_content': item.text_content,
                    }
                    # Encode image data as base64
                    if item.image_data:
                        item_data['image_data'] = base64.b64encode(item.image_data).decode('ascii')
                    data.append(item_data)
            
            with open(self.HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"[ClipboardMonitor] Saved {len(data)} items to history")
        except Exception as e:
            print(f"[ClipboardMonitor] Error saving history: {e}")
    
    def get_history(self) -> List[ClipboardItem]:
        """Get clipboard history (thread-safe)."""
        with self._lock:
            return list(self.history)

    def clear_history(self):
        """Clear all clipboard history."""
        with self._lock:
            self.history.clear()
        self._save_history()
        print("[ClipboardMonitor] History cleared")
    
    def delete_item(self, index: int) -> bool:
        """Delete a specific item from history by index."""
        deleted = False
        with self._lock:
            if 0 <= index < len(self.history):
                deleted_item = self.history.pop(index)
                print(f"[ClipboardMonitor] Deleted item at index {index}: {deleted_item.preview[:30]}...")
                deleted = True
            else:
                print(f"[ClipboardMonitor] Invalid index {index}, history size is {len(self.history)}")
        
        # Save outside of lock to prevent deadlock
        if deleted:
            self._save_history()
        
        return deleted
    
    def _poll_loop(self):
        """Background polling loop."""
        print("[ClipboardMonitor] Starting polling loop...")
        poll_count = 0
        while self._running:
            try:
                self._check_clipboard()
                poll_count += 1
                if poll_count % 10 == 0:  # Log every 3 seconds
                    print(f"[ClipboardMonitor] Polling... (count={poll_count}, history_size={len(self.history)})")
            except Exception as e:
                print(f"[ClipboardMonitor] Error: {e}")
            time.sleep(0.3)  # Poll every 300ms
    
    def _check_clipboard(self):
        """Check if clipboard content has changed."""
        current_count = self._pasteboard.changeCount()
        
        if current_count != self._last_change_count:
            print(f"[ClipboardMonitor] Change detected! count: {self._last_change_count} -> {current_count}")
            self._last_change_count = current_count
            
            # Check for text content
            text_content = self._pasteboard.stringForType_(NSPasteboardTypeString)
            has_text = text_content and text_content.strip()
            
            # Check for image content
            image = None
            image_data = None
            thumbnail = None
            
            # Try PNG first, then TIFF
            types = self._pasteboard.types()
            if types:
                if NSPasteboardTypePNG in types:
                    png_data = self._pasteboard.dataForType_(NSPasteboardTypePNG)
                    if png_data:
                        image = NSImage.alloc().initWithData_(png_data)
                        image_data = bytes(png_data)
                elif NSPasteboardTypeTIFF in types:
                    tiff_data = self._pasteboard.dataForType_(NSPasteboardTypeTIFF)
                    if tiff_data:
                        image = NSImage.alloc().initWithData_(tiff_data)
                        if image:
                            image_data = image_to_png_data(image)
            
            has_image = image is not None and image_data is not None
            
            if has_image:
                thumbnail = create_thumbnail(image, 32)
            
            # Determine content type and create item
            if has_text and has_image:
                content_type = "mixed"
                if self.debug:
                    print(f"[ClipboardMonitor] New mixed content: {text_content[:30]}... + image")
            elif has_image:
                content_type = "image"
                if self.debug:
                    print(f"[ClipboardMonitor] New image content")
            elif has_text:
                content_type = "text"
                if self.debug:
                    safe_preview = text_content[:50].encode('ascii', 'replace').decode('ascii')
                    print(f"[ClipboardMonitor] New text content: {safe_preview}...")
            else:
                if self.debug:
                    print("[ClipboardMonitor] No recognized content type")
                return
            
            self._add_to_history(content_type, text_content if has_text else None, image_data, thumbnail)
    
    def _add_to_history(self, content_type: str, text_content: Optional[str], 
                        image_data: Optional[bytes], thumbnail):
        """Add new content to history."""
        with self._lock:
            # For deduplication, remove any existing identical items
            if content_type == "text" and text_content:
                self.history = [item for item in self.history 
                               if not (item.content_type == "text" and item.text_content == text_content)]
            elif content_type == "image" and image_data:
                self.history = [item for item in self.history 
                               if not (item.content_type == "image" and item.image_data == image_data)]
            elif content_type == "mixed" and text_content and image_data:
                 self.history = [item for item in self.history 
                               if not (item.content_type == "mixed" and 
                                       item.text_content == text_content and 
                                       item.image_data == image_data)]
            
            # Add to front
            item = ClipboardItem(
                content_type=content_type,
                timestamp=datetime.now(),
                text_content=text_content,
                image_data=image_data,
                thumbnail=thumbnail
            )
            self.history.insert(0, item)
            
            # Trim to max size
            if len(self.history) > self.max_history:
                self.history = self.history[:self.max_history]
        
        # Persist to disk
        self._save_history()
        
        # Notify callback
        if self.on_change:
            preview = text_content[:50] if text_content else f"[{content_type}]"
            self.on_change(preview)
