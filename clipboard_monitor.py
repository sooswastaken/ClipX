"""Clipboard Monitor - Polls NSPasteboard for changes and maintains history.
Supports text and image content with persistent storage.
Images are stored on disk and loaded lazily to minimize memory usage.
"""

import base64
import hashlib
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
    NSData,
)


# --- Storage paths ---
STORAGE_DIR = Path.home() / "Library" / "Application Support" / "ClipX"
IMAGES_DIR = STORAGE_DIR / "images"
HISTORY_FILE = STORAGE_DIR / "history.json"

# Max dimension for stored images (saves disk and memory when loaded)
MAX_IMAGE_DIM = 512


@dataclass
class ClipboardItem:
    """A single clipboard history item supporting text and images.
    Images are stored on disk; only a small thumbnail is kept in memory.
    """
    content_type: str  # "text", "image", or "mixed"
    timestamp: datetime
    text_content: Optional[str] = None
    image_path: Optional[str] = None       # Path to on-disk PNG
    thumbnail: Optional[object] = field(default=None, repr=False)  # NSImage, small
    
    # --- DEPRECATED: kept only for migration from old format ---
    image_data: Optional[bytes] = field(default=None, repr=False)
    
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
        return self.image_path is not None or self.image_data is not None
    
    def load_image_data(self) -> Optional[bytes]:
        """Load full image data from disk on demand. Returns PNG bytes or None."""
        # Legacy in-memory data (shouldn't happen after migration)
        if self.image_data is not None:
            return self.image_data
        if self.image_path and os.path.exists(self.image_path):
            try:
                with open(self.image_path, 'rb') as f:
                    return f.read()
            except Exception as e:
                print(f"[ClipboardItem] Error loading image from {self.image_path}: {e}")
        return None


def create_thumbnail(image: 'NSImage', size: int = 32) -> 'NSImage':
    """Create a square thumbnail from an NSImage."""
    try:
        orig_size = image.size()
        scale = max(size / orig_size.width, size / orig_size.height)
        new_width = orig_size.width * scale
        new_height = orig_size.height * scale
        
        thumbnail = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
        thumbnail.lockFocus()
        
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


def _downscale_png(png_bytes: bytes, max_dim: int = MAX_IMAGE_DIM) -> bytes:
    """Downscale PNG data so the longest edge is at most max_dim pixels.
    Returns the (possibly smaller) PNG bytes."""
    try:
        ns_data = NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
        image = NSImage.alloc().initWithData_(ns_data)
        if not image:
            return png_bytes
        
        orig = image.size()
        if orig.width <= max_dim and orig.height <= max_dim:
            return png_bytes  # Already small enough
        
        scale = min(max_dim / orig.width, max_dim / orig.height)
        new_w = int(orig.width * scale)
        new_h = int(orig.height * scale)
        
        resized = NSImage.alloc().initWithSize_(NSMakeSize(new_w, new_h))
        resized.lockFocus()
        image.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(0, 0, new_w, new_h),
            NSMakeRect(0, 0, orig.width, orig.height),
            NSCompositingOperationCopy,
            1.0
        )
        resized.unlockFocus()
        
        result = image_to_png_data(resized)
        return result if result else png_bytes
    except Exception:
        return png_bytes


def _save_image_to_disk(png_bytes: bytes) -> Optional[str]:
    """Save PNG bytes to the images directory and return the file path."""
    try:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        # Use content hash as filename for deduplication
        digest = hashlib.sha256(png_bytes).hexdigest()[:16]
        path = IMAGES_DIR / f"{digest}.png"
        if not path.exists():
            with open(path, 'wb') as f:
                f.write(png_bytes)
        return str(path)
    except Exception as e:
        print(f"[ClipboardMonitor] Error saving image to disk: {e}")
        return None


class ClipboardMonitor:
    """
    Monitors the system clipboard for changes.
    Uses polling since NSPasteboard doesn't provide change notifications.
    Supports text and image content.
    """
    
    def __init__(self, on_change: Optional[Callable[[str], None]] = None, max_history: int = 25, debug: bool = False):
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
        """Load history from disk. Images are NOT loaded into memory — only paths are restored."""
        try:
            if not HISTORY_FILE.exists():
                print("[ClipboardMonitor] No history file found, starting fresh")
                return
            
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for item_data in data:
                image_path = item_data.get('image_path')
                thumbnail = None
                
                # Migrate old format: inline base64 image_data -> disk file
                if not image_path and item_data.get('image_data'):
                    raw = base64.b64decode(item_data['image_data'])
                    raw = _downscale_png(raw)
                    image_path = _save_image_to_disk(raw)
                
                # Create thumbnail from on-disk image (small, ~4KB)
                if image_path and os.path.exists(image_path):
                    try:
                        ns_data = NSData.dataWithBytes_length_(
                            open(image_path, 'rb').read(), 
                            os.path.getsize(image_path)
                        )
                        img = NSImage.alloc().initWithData_(ns_data)
                        if img:
                            thumbnail = create_thumbnail(img, 32)
                        # img is released — we don't keep it
                    except Exception:
                        pass
                
                item = ClipboardItem(
                    content_type=item_data['content_type'],
                    timestamp=datetime.fromisoformat(item_data['timestamp']),
                    text_content=item_data.get('text_content'),
                    image_path=image_path,
                    thumbnail=thumbnail,
                )
                self.history.append(item)
            
            print(f"[ClipboardMonitor] Loaded {len(self.history)} items from history")
        except Exception as e:
            print(f"[ClipboardMonitor] Error loading history: {e}")
    
    def _save_history(self):
        """Save history to disk. Image bytes are already on disk — only paths are persisted."""
        try:
            STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            
            data = []
            with self._lock:
                for item in self.history:
                    item_data = {
                        'content_type': item.content_type,
                        'timestamp': item.timestamp.isoformat(),
                        'text_content': item.text_content,
                    }
                    if item.image_path:
                        item_data['image_path'] = item.image_path
                    data.append(item_data)
            
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
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
        # Clean up orphaned image files
        self._cleanup_images()
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
        
        if deleted:
            self._save_history()
            self._cleanup_images()
        
        return deleted
    
    def _cleanup_images(self):
        """Remove image files that are no longer referenced by any history item."""
        try:
            if not IMAGES_DIR.exists():
                return
            referenced = set()
            with self._lock:
                for item in self.history:
                    if item.image_path:
                        referenced.add(item.image_path)
            for img_file in IMAGES_DIR.iterdir():
                if str(img_file) not in referenced:
                    try:
                        img_file.unlink()
                    except Exception:
                        pass
        except Exception:
            pass
    
    def _poll_loop(self):
        """Background polling loop."""
        import objc
        print("[ClipboardMonitor] Starting polling loop...")
        poll_count = 0
        while self._running:
            try:
                with objc.autorelease_pool():
                    self._check_clipboard()
                    poll_count += 1
                    if poll_count % 10 == 0:
                        print(f"[ClipboardMonitor] Polling... (count={poll_count}, history_size={len(self.history)})")
            except Exception as e:
                print(f"[ClipboardMonitor] Error: {e}")
            time.sleep(0.3)
    
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
            
            # Downscale + save image to disk, then discard raw bytes
            image_path = None
            if has_image and image_data:
                image_data = _downscale_png(image_data)
                image_path = _save_image_to_disk(image_data)
                # Don't keep raw bytes in memory
            
            self._add_to_history(content_type, text_content if has_text else None, image_path, thumbnail)
    
    def _add_to_history(self, content_type: str, text_content: Optional[str], 
                        image_path: Optional[str], thumbnail):
        """Add new content to history."""
        with self._lock:
            # For deduplication, remove any existing identical items
            if content_type == "text" and text_content:
                self.history = [item for item in self.history 
                               if not (item.content_type == "text" and item.text_content == text_content)]
            elif content_type == "image" and image_path:
                self.history = [item for item in self.history 
                               if not (item.content_type == "image" and item.image_path == image_path)]
            elif content_type == "mixed" and text_content and image_path:
                 self.history = [item for item in self.history 
                               if not (item.content_type == "mixed" and 
                                       item.text_content == text_content and 
                                       item.image_path == image_path)]
            
            item = ClipboardItem(
                content_type=content_type,
                timestamp=datetime.now(),
                text_content=text_content,
                image_path=image_path,
                thumbnail=thumbnail,
            )
            self.history.insert(0, item)
            
            if len(self.history) > self.max_history:
                self.history = self.history[:self.max_history]
        
        # Persist to disk
        self._save_history()
        self._cleanup_images()
        
        # Notify callback
        if self.on_change:
            preview = text_content[:50] if text_content else f"[{content_type}]"
            self.on_change(preview)
