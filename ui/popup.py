"""
ClipboardPopup - The main clipboard history popup window.
A borderless, floating panel with glassmorphism effect.
"""

from typing import List, Callable, Optional

from AppKit import (
    NSPanel,
    NSView,
    NSColor,
    NSVisualEffectView,
    NSWindow,
    NSScreen,
    NSApplication,
    NSPasteboard,
    NSPasteboardTypeString,
    NSPasteboardTypePNG,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSScreenSaverWindowLevel,
    NSEvent,
    NSAnimationContext,
    NSTimer,
    NSMakeRect,
    NSMakePoint
)
import objc

from clipboard_monitor import ClipboardItem
from .constants import POPUP_WIDTH, POPUP_MAX_HEIGHT, ITEM_HEIGHT, PADDING, CORNER_RADIUS, EDIT_BUTTON_HEIGHT
from .item_view import ClipboardItemView
from .edit_button_view import EditButtonView
from .animations import PopupAnimationMixin
from .focus_manager import FocusManager

class ClipboardPopup(NSPanel, PopupAnimationMixin):
    """
    The main clipboard history popup window.
    A borderless, floating panel with glassmorphism effect.
    """
    
    def _setup_click_outside_monitor(self):
        """Set up a global monitor to detect clicks outside the popup."""
        if hasattr(self, '_click_monitor') and self._click_monitor:
            return

        def handle_click(event):
            # If we are visible and click is outside our frame
            if self._is_visible:
                # content_rect = self.contentView().frame()
                # If the event window is not us, hide
                if event.window() != self:
                    self.hide()
                return event
        
        # Monitor global mouse clicks
        self._click_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            1 << 0 | 1 << 1, # LeftMouseDown | LeftMouseUp
            handle_click
        )

    @classmethod
    def create(cls, on_select: Optional[Callable[[ClipboardItem], None]] = None):
        try:
            # Create panel
            panel = cls.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, POPUP_WIDTH, 0),
                0, # NSWindowStyleMaskBorderless
                2, # NSBackingStoreBuffered
                False
            )
            
            # Initialize state
            panel._items = []
            panel._item_views = []
            panel._edit_button_view = None
            panel._is_visible = False
            panel._on_select = on_select
            panel._on_delete = None
            panel._selected_index = 0
            panel._is_edit_mode = False
            
            # Initialize FocusManager
            panel.focus_manager = FocusManager()
            
            # Configure window
            panel.setLevel_(NSScreenSaverWindowLevel)
            panel.setBackgroundColor_(NSColor.clearColor())
            panel.setOpaque_(False)
            panel.setHasShadow_(True)
            panel.setHidesOnDeactivate_(False)
            panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces |
                NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            panel.setAcceptsMouseMovedEvents_(True)
            
            print("[Popup] Panel configured.", flush=True)
            
            panel._setup_content_view()
            print("[Popup] Content view created.", flush=True)
            
            return panel
        except Exception as e:
            print(f"[Popup] ERROR creating popup: {e}", flush=True)
            import traceback
            traceback.print_exc()
            raise
    
    def set_on_delete_callback(self, callback):
        self._on_delete = callback
    
    def _create_noise_texture(self, width, height):
        """Create a grey noise texture image for grain effect."""
        import random
        from Quartz import (
            CGBitmapContextCreate, CGBitmapContextCreateImage,
            CGColorSpaceCreateDeviceGray, kCGImageAlphaNone
        )
        
        width = max(width, 64)
        height = max(height, 64)
        
        # Create greyscale pixel data with random noise
        pixels = bytearray(width * height)
        for i in range(len(pixels)):
            # Random grey values between 100-156 (subtle light/dark grey variation)
            pixels[i] = random.randint(100, 156)
        
        # Create CGImage from pixel data
        colorspace = CGColorSpaceCreateDeviceGray()
        context = CGBitmapContextCreate(
            pixels, width, height, 8, width, colorspace, kCGImageAlphaNone
        )
        
        if context:
            return CGBitmapContextCreateImage(context)
        return None

    def _setup_content_view(self):
        """Set up the glass-effect content view with frosted grain texture."""
        content_frame = self.contentView().bounds()
        
        # Visual effect view for blur
        self._blur_view = NSVisualEffectView.alloc().initWithFrame_(content_frame)
        self._blur_view.setMaterial_(13)  # .hudWindow - more transparent
        self._blur_view.setBlendingMode_(0)  # .behindWindow
        self._blur_view.setState_(1)  # .active - ensures effect is always visible
        self._blur_view.setWantsLayer_(True)
        self._blur_view.layer().setCornerRadius_(CORNER_RADIUS)
        self._blur_view.layer().setMasksToBounds_(True)
        self._blur_view.setAutoresizingMask_(18)
        # Make the blur view itself more transparent
        self._blur_view.setAlphaValue_(0.85)
        
        self.contentView().addSubview_(self._blur_view)
        
        # Add noise grain overlay for frosted glass effect
        self._grain_view = NSView.alloc().initWithFrame_(content_frame)
        self._grain_view.setWantsLayer_(True)
        self._grain_view.setAutoresizingMask_(18)
        grain_layer = self._grain_view.layer()
        if grain_layer:
            grain_layer.setCornerRadius_(CORNER_RADIUS)
            grain_layer.setMasksToBounds_(True)
            # Create actual noise texture
            try:
                noise_image = self._create_noise_texture(int(content_frame.size.width) or 320, 
                                                          int(content_frame.size.height) or 400)
                if noise_image:
                    grain_layer.setContents_(noise_image)
                    grain_layer.setContentsGravity_("resize")
                    grain_layer.setOpacity_(0.15)  # Adjust grain intensity
            except Exception as e:
                print(f"[GlassEffect] Noise texture error: {e}", flush=True)
        self._blur_view.addSubview_(self._grain_view)
        
        # Container for items
        self._items_container = NSView.alloc().initWithFrame_(content_frame)
        self._items_container.setAutoresizingMask_(18)
        self._items_container.setWantsLayer_(True)
        self._blur_view.addSubview_(self._items_container)
        
        # Selection Highlight View
        self._selection_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 0))
        self._selection_view.setWantsLayer_(True)
        
        layer = self._selection_view.layer()
        if layer:
            layer.setBackgroundColor_(NSColor.colorWithWhite_alpha_(1.0, 0.15).CGColor())
            layer.setCornerRadius_(6.0)
            layer.setBorderWidth_(1.0)
            layer.setBorderColor_(NSColor.colorWithWhite_alpha_(1.0, 0.1).CGColor())
            
            layer.setShadowColor_(NSColor.blackColor().CGColor())
            layer.setShadowOpacity_(0.2)
            layer.setShadowOffset_(NSMakePoint(0, -2))
            layer.setShadowRadius_(4)
        
        self._items_container.addSubview_(self._selection_view)
    
    def update_items(self, items: List[ClipboardItem]):
        """Update the displayed clipboard items."""
        self._items = items[:50]
        self._selected_index = 0
        self._rebuild_item_views()
    
    def _rebuild_item_views(self):
        """Rebuild the item views list."""
        from AppKit import NSScrollView
        
        # Clear old views
        for view in self._item_views:
            view.removeFromSuperview()
        self._item_views.clear()
        
        # Remove old edit button if exists
        if self._edit_button_view:
            self._edit_button_view.removeFromSuperview()
            self._edit_button_view = None
        
        # Reset edit mode on rebuild
        self._is_edit_mode = False
        
        if not self._items:
            return
        
        # Calculate heights - add space for edit button at top
        num_items = len(self._items)
        items_height = ITEM_HEIGHT * num_items
        edit_button_space = EDIT_BUTTON_HEIGHT + PADDING
        total_content_height = items_height + edit_button_space + (PADDING * 3)
        visible_height = min(total_content_height, POPUP_MAX_HEIGHT)
        
        # Resize window
        frame = self.frame()
        frame.size.height = visible_height
        self.setFrame_display_(frame, True)
        
        # Resize blur view
        blur_bounds = self.contentView().bounds()
        self._blur_view.setFrame_(blur_bounds)
        
        # Set up scroll view
        if not hasattr(self, '_scroll_view') or self._scroll_view is None:
            self._scroll_view = NSScrollView.alloc().initWithFrame_(blur_bounds)
            self._scroll_view.setHasVerticalScroller_(True)
            self._scroll_view.setHasHorizontalScroller_(False)
            self._scroll_view.setAutohidesScrollers_(True)
            self._scroll_view.setDrawsBackground_(False)
            self._scroll_view.setBorderType_(0)
            self._scroll_view.setScrollerStyle_(1)
            self._blur_view.addSubview_(self._scroll_view)
        
        self._scroll_view.setFrame_(blur_bounds)
        
        self._items_container = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, blur_bounds.size.width, total_content_height)
        )
        self._items_container.setWantsLayer_(True)
        self._scroll_view.setDocumentView_(self._items_container)
        
        # Add selection view to the new container
        if hasattr(self, '_selection_view'):
            self._selection_view.removeFromSuperview()
            self._items_container.addSubview_(self._selection_view)
            
            # Position for first clipboard item (index 1, after edit button)
            if self._items:
                y = total_content_height - PADDING - edit_button_space - ITEM_HEIGHT
                start_frame = NSMakeRect(PADDING, y, blur_bounds.size.width - (PADDING * 2), ITEM_HEIGHT)
                self._selection_view.setFrame_(start_frame)
                self._selection_view.setHidden_(False)
            else:
                self._selection_view.setHidden_(True)
        
        inner_width = blur_bounds.size.width - (PADDING * 2)
        
        # Create edit button at top-right (index 0)
        edit_btn_width = 64
        edit_btn_x = blur_bounds.size.width - PADDING - edit_btn_width
        edit_btn_y = total_content_height - PADDING - EDIT_BUTTON_HEIGHT
        
        self._edit_button_view = EditButtonView.alloc_with_callbacks(
            edit_btn_width,
            on_click=self._toggle_edit_mode,
            on_hover=self._on_item_hovered,
            index=0
        )
        self._edit_button_view.setFrame_(NSMakeRect(edit_btn_x, edit_btn_y, edit_btn_width, EDIT_BUTTON_HEIGHT))
        self._items_container.addSubview_(self._edit_button_view)
        
        # Create item views (indices 1+)
        for i, item in enumerate(self._items):
            actual_index = i + 1  # Shift indices by 1 for edit button
            y = total_content_height - PADDING - edit_button_space - ((i + 1) * ITEM_HEIGHT)
            view = ClipboardItemView.alloc_with_item(
                item, actual_index, inner_width, 
                on_click=self._on_item_clicked,
                on_hover=self._on_item_hovered,
                on_delete=self._on_item_delete
            )
            view.setFrame_(NSMakeRect(PADDING, y, inner_width, ITEM_HEIGHT))
            if actual_index == 1:
                view.set_selected(True)
            self._items_container.addSubview_(view)
            self._item_views.append(view)
        
        # Default selection is first clipboard item (index 1)
        self._selected_index = 1
        
        # Scroll to top
        if self._items:
            self._scroll_to_item(1)
    
    def show_at_position(self, x: float, y: float, show_above: bool = False):
        """Show the popup at the specified position with animation."""
        actual_x = x - POPUP_WIDTH / 2
        actual_y = y
        
        if show_above:
            start_y = actual_y + 10
        else:
            start_y = actual_y - 10
        
        self.setFrameOrigin_(NSMakePoint(actual_x, start_y))
        self.setAlphaValue_(0.0)
        
        app = NSApplication.sharedApplication()
        app.activateIgnoringOtherApps_(True)
        
        self.makeKeyAndOrderFront_(None)
        self.orderFrontRegardless()
        self._is_visible = True
        
        self._setup_click_outside_monitor()
        
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.15)
        self.animator().setFrameOrigin_(NSMakePoint(actual_x, actual_y))
        self.animator().setAlphaValue_(1.0)
        NSAnimationContext.endGrouping()
    
    def hide(self, refocus: bool = True, animate: bool = True):
        """Hide the popup with animation."""
        if animate:
            self._animate_hide() # From Mixin
        else:
            self.orderOut_(None)
            self._is_visible = False
            
        if refocus:
            self.focus_manager.refocus_original_element()
            self.focus_manager.refocus_original_app()
    
    def move_selection(self, delta: int):
        """Move selection up or down. Index 0 = edit button, 1+ = items."""
        if not self._item_views:
            return
        
        # Deselect current
        if self._selected_index == 0:
            if self._edit_button_view:
                self._edit_button_view.set_selected(False)
        elif 1 <= self._selected_index <= len(self._item_views):
            self._item_views[self._selected_index - 1].set_selected(False)
        
        # Calculate new index (0 = edit button, 1 to len(_items) = items)
        max_index = len(self._items)  # Items are 1-indexed now
        self._selected_index = max(0, min(max_index, self._selected_index + delta))
        
        # Select new
        if self._selected_index == 0:
            if self._edit_button_view:
                self._edit_button_view.set_selected(True)
            self._selection_view.setHidden_(False)
            self._animate_selection_change() # From Mixin
        else:
            self._item_views[self._selected_index - 1].set_selected(True)
            self._selection_view.setHidden_(False)
            self._animate_selection_change() # From Mixin
            self._scroll_to_item(self._selected_index)
    
    def confirm_selection(self):
        """Confirm the current selection - toggle edit mode, delete, or paste."""
        print(f"[Popup] confirm_selection called, selected_index={self._selected_index}, edit_mode={self._is_edit_mode}", flush=True)
        
        # Index 0 = edit button - toggle edit mode
        if self._selected_index == 0:
            self._toggle_edit_mode()
            return
        
        # If in edit mode, delete the selected item
        if self._is_edit_mode:
            item_index = self._selected_index - 1  # Convert to 0-based item index
            self._delete_item_at_index(item_index)
            return
        
        # Normal mode - paste the selected item
        item_index = self._selected_index - 1
        if item_index < 0 or item_index >= len(self._items):
            print("[Popup] No items or invalid index", flush=True)
            return
        
        item = self._items[item_index]
        print(f"[Popup] Selected item: {item.preview[:30]}...", flush=True)
        
        # Put on clipboard
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        
        if hasattr(item, 'content_type'):
            img_bytes = item.load_image_data() if item.has_image() else None
            if item.content_type == "image" and img_bytes:
                from AppKit import NSData
                png_data = NSData.dataWithBytes_length_(img_bytes, len(img_bytes))
                pasteboard.setData_forType_(png_data, NSPasteboardTypePNG)
                print("[Popup] Image placed on clipboard", flush=True)
            elif item.content_type == "mixed" and img_bytes and item.text_content:
                from AppKit import NSData
                png_data = NSData.dataWithBytes_length_(img_bytes, len(img_bytes))
                pasteboard.setData_forType_(png_data, NSPasteboardTypePNG)
                pasteboard.setString_forType_(item.text_content, NSPasteboardTypeString)
                print("[Popup] Mixed content placed on clipboard", flush=True)
            else:
                pasteboard.setString_forType_(item.text_content or item.content, NSPasteboardTypeString)
                print("[Popup] Text placed on clipboard", flush=True)
        else:
            pasteboard.setString_forType_(item.content, NSPasteboardTypeString)
            print("[Popup] Content placed on clipboard", flush=True)
        
        self.hide(refocus=False)
        
        if self._on_select:
            self._on_select(item)
        
        # Schedule Focus/Paste sequence
        def trigger_paste(timer):
             self.focus_manager.perform_paste_sequence()

        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            0.15, False, trigger_paste
        )

    def _on_item_clicked(self, index: int):
        """Handle click on a clipboard item. Index is 1-based for items."""
        # Deselect current
        if self._selected_index == 0:
            if self._edit_button_view:
                self._edit_button_view.set_selected(False)
        elif 1 <= self._selected_index <= len(self._item_views):
            self._item_views[self._selected_index - 1].set_selected(False)
        
        self._selected_index = index
        
        # Select new
        if index == 0:
            if self._edit_button_view:
                self._edit_button_view.set_selected(True)
            self._selection_view.setHidden_(False)
            self._animate_selection_change()
        else:
            self._item_views[index - 1].set_selected(True)
            self._selection_view.setHidden_(False)
            self._animate_selection_change()
        
        self.confirm_selection()
    
    def _on_item_hovered(self, index: int):
        """Handle mouse hover on a clipboard item. Index is 0 for edit button, 1+ for items."""
        if index == self._selected_index:
            return
        
        # Deselect current
        if self._selected_index == 0:
            if self._edit_button_view:
                self._edit_button_view.set_selected(False)
        elif 1 <= self._selected_index <= len(self._item_views):
            self._item_views[self._selected_index - 1].set_selected(False)
        
        self._selected_index = index
        
        # Select new
        if index == 0:
            if self._edit_button_view:
                self._edit_button_view.set_selected(True)
            self._selection_view.setHidden_(False)
            self._animate_selection_change()
        else:
            self._item_views[index - 1].set_selected(True)
            self._selection_view.setHidden_(False)
            self._animate_selection_change()
    
    def _scroll_to_item(self, index: int):
        """Scroll the scroll view to make the item at index visible. Index is 1-based for items."""
        if not hasattr(self, '_scroll_view') or self._scroll_view is None:
            return
        
        content_height = self._items_container.frame().size.height
        visible_height = self._scroll_view.documentVisibleRect().size.height
        
        # For edit button (index 0) or first item, scroll to top
        if index <= 1:
            top_point = NSMakePoint(0, content_height)
            self._items_container.scrollPoint_(top_point)
            return
        
        item_index = index - 1
        if not self._item_views or item_index < 0 or item_index >= len(self._item_views):
            return
        
        item_view = self._item_views[item_index]
        item_frame = item_view.frame()
        
        # Get current scroll position (Y coordinate of the visible rect's origin)
        current_visible_rect = self._scroll_view.documentVisibleRect()
        current_scroll_y = current_visible_rect.origin.y
        
        # Calculate the top and bottom of the visible area
        visible_top = current_scroll_y + visible_height
        visible_bottom = current_scroll_y
        
        # Calculate item's top and bottom positions
        item_top = item_frame.origin.y + item_frame.size.height
        item_bottom = item_frame.origin.y
        
        # For the last item, include bottom padding
        if item_index == len(self._item_views) - 1:
            item_bottom -= (PADDING * 3)
        
        # Check if item is already fully visible
        if item_top <= visible_top and item_bottom >= visible_bottom:
            return  # Already visible, no scroll needed
        
        # Scroll down: if item bottom is below visible area
        if item_bottom < visible_bottom:
            # Scroll down by exactly one item height
            new_scroll_y = current_scroll_y - ITEM_HEIGHT
            # Clamp to not go below 0
            new_scroll_y = max(0, new_scroll_y)
            scroll_point = NSMakePoint(0, new_scroll_y)
            self._items_container.scrollPoint_(scroll_point)
        
        # Scroll up: if item top is above visible area
        elif item_top > visible_top:
            # Scroll up by exactly one item height
            new_scroll_y = current_scroll_y + ITEM_HEIGHT
            # Clamp to not exceed content bounds
            max_scroll_y = content_height - visible_height
            new_scroll_y = min(max_scroll_y, new_scroll_y)
            scroll_point = NSMakePoint(0, new_scroll_y)
            self._items_container.scrollPoint_(scroll_point)
    
    def _on_item_delete(self, index: int):
        """Handle delete button click on an item. Index is 1-based."""
        item_index = index - 1
        self._delete_item_at_index(item_index)
    
    def _toggle_edit_mode(self):
        """Toggle edit mode on/off."""
        self._is_edit_mode = not self._is_edit_mode
        print(f"[Popup] Edit mode: {self._is_edit_mode}", flush=True)
        
        # Update edit button text
        if self._edit_button_view:
            self._edit_button_view.set_edit_mode(self._is_edit_mode)
        
        # Update all item views
        for view in self._item_views:
            view.set_edit_mode(self._is_edit_mode)
    
    def _delete_item_at_index(self, item_index: int):
        """Delete an item with animation. item_index is 0-based into _items.
        Uses queue-based system to allow spamming delete while animations are in progress."""
        try:
            if item_index < 0 or item_index >= len(self._items):
                print(f"[Popup] Invalid delete index: {item_index}", flush=True)
                return
            
            print(f"[Popup] Queuing deletion for item at index {item_index}", flush=True)
            
            # Queue the entire deletion operation - data removal + animation
            # The queue processor will call the callback and delete from _items in sequence
            self._queue_item_deletion(
                view_index=item_index,
                on_delete_callback=self._on_delete,
                item_index=item_index
            )
        except Exception as e:
            print(f"[Popup] EXCEPTION in _delete_item_at_index: {e}", flush=True)
            import traceback
            traceback.print_exc()

    def store_focused_element(self, element):
        """Delegate to FocusManager."""
        self.focus_manager.store_focused_element(element)
    
    def store_frontmost_app(self, app):
        """Delegate to FocusManager."""
        self.focus_manager.store_frontmost_app(app)
    
    def select_and_confirm_item(self, item_number: int):
        """Directly select and paste item by number (1-based). Number 1 = most recent."""
        if item_number < 1 or item_number > len(self._items):
            print(f"[Popup] Item {item_number} not in history (have {len(self._items)})", flush=True)
            return
        
        # item_number maps to internal index (1-based, matching _item_views)
        internal_index = item_number
        
        # Deselect current
        if self._selected_index == 0:
            if self._edit_button_view:
                self._edit_button_view.set_selected(False)
        elif 1 <= self._selected_index <= len(self._item_views):
            self._item_views[self._selected_index - 1].set_selected(False)
        
        self._selected_index = internal_index
        self._item_views[internal_index - 1].set_selected(True)
        self.confirm_selection()
    
    # macOS keyCode -> number: 18=1, 19=2, 20=3, 21=4, 23=5, 22=6, 26=7, 28=8
    _NUMBER_KEYCODES = {18: 1, 19: 2, 20: 3, 21: 4, 23: 5, 22: 6, 26: 7, 28: 8}
    
    def keyDown_(self, event):
        """Handle keyboard events."""
        key_code = event.keyCode()
        
        if key_code == 126:  # Arrow up
            self.move_selection(-1)
        elif key_code == 125:  # Arrow down
            self.move_selection(1)
        elif key_code == 36:  # Enter / Return
            self.confirm_selection()
        elif key_code == 53:  # Escape
            self.hide()
        elif key_code in self._NUMBER_KEYCODES:
            self.select_and_confirm_item(self._NUMBER_KEYCODES[key_code])
        else:
            pass
    
    def canBecomeKeyWindow(self):
        return True
    
    def canBecomeMainWindow(self):
        return False
    
    def resignKeyWindow(self):
        """Called when the window loses key status."""
        objc.super(ClipboardPopup, self).resignKeyWindow()
        if self._is_visible:
            print("[Popup] Lost key window status, hiding with animation...", flush=True)
            self._animate_hide()
