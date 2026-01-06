"""
Clipboard Popup Window - Modern floating panel with smooth animations.
"""

from typing import List, Callable, Optional

from AppKit import (
    NSPanel,
    NSView,
    NSTextField,
    NSColor,
    NSFont,
    NSFontManager,
    NSScreen,
    NSCursor,
    NSVisualEffectView,
    NSVisualEffectMaterial,
    NSVisualEffectBlendingMode,
    NSTrackingArea,
    NSTrackingMouseEnteredAndExited,
    NSTrackingMouseMoved,
    NSTrackingActiveAlways,
    NSTrackingInVisibleRect,
    NSBorderlessWindowMask,
    NSWindowStyleMaskBorderless,
    NSBackingStoreBuffered,
    NSFloatingWindowLevel,
    NSScreenSaverWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSMakeRect,
    NSMakePoint,
    NSApplication,
    NSPasteboard,
    NSPasteboardTypeString,
    NSPasteboardTypePNG,
    NSEvent,
    NSEventTypeKeyDown,
    NSValue,
)
from Quartz import (
    CATransaction,
    kCAMediaTimingFunctionEaseOut,
    CAMediaTimingFunction,
    CASpringAnimation,
    CALayer,
)
import objc

from clipboard_monitor import ClipboardItem
from accessibility import ElementRect


# UI Constants
POPUP_WIDTH = 320
POPUP_MAX_HEIGHT = 400
ITEM_HEIGHT = 76
PADDING = 8
CORNER_RADIUS = 12
ANIMATION_DURATION = 0.18


class ClipboardItemView(NSView):
    """A single clipboard item row in the popup."""
    
    @classmethod
    def alloc_with_item(cls, item: ClipboardItem, index: int, width: float, 
                        on_click: Optional[Callable[[int], None]] = None,
                        on_hover: Optional[Callable[[int], None]] = None):
        view = cls.alloc().initWithFrame_(NSMakeRect(0, 0, width, ITEM_HEIGHT))
        view._item = item
        view._index = index
        # view._is_hovered = False  # Removed: Unified with selection
        view._is_selected = False
        view._on_click = on_click
        view._on_hover = on_hover
        view._setup_label()
        view._setup_tracking()
        return view
    
    def _setup_label(self):
        """Create the text label and optional image thumbnail."""
        from AppKit import (
            NSImageView, 
            NSImageScaleProportionallyUpOrDown, 
            NSImage, 
            NSTextAlignmentRight,
            NSMutableAttributedString,
            NSForegroundColorAttributeName,
            NSFontAttributeName
        )
        
        # Check if item has an image thumbnail
        has_thumbnail = hasattr(self._item, 'has_image') and self._item.has_image() and self._item.thumbnail
        
        # Thumbnail size and position
        thumb_size = 32
        thumb_margin = 6
        
        if has_thumbnail:
            label_x = PADDING + thumb_size + thumb_margin
            label_width = self.frame().size.width - label_x - PADDING
            
            # Create image view for thumbnail
            self._thumbnail_view = NSImageView.alloc().initWithFrame_(
                NSMakeRect(PADDING, (ITEM_HEIGHT - thumb_size) / 2, thumb_size, thumb_size)
            )
            self._thumbnail_view.setImage_(self._item.thumbnail)
            self._thumbnail_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
            self._thumbnail_view.setWantsLayer_(True)
            self._thumbnail_view.layer().setCornerRadius_(4)
            self._thumbnail_view.layer().setMasksToBounds_(True)
            self.addSubview_(self._thumbnail_view)
        else:
            label_x = PADDING
            label_width = self.frame().size.width - PADDING * 2
        
        if self._item.content_type == "image":
            # Add SVG icon (SF Symbol)
            # Move more to the right as requested (+12)
            label_x += 12
            
            icon_size = 14
            # Center icon vertically in the 76px item. Center is 38.
            # 38 - 7 = 31.
            icon_view = NSImageView.alloc().initWithFrame_(
                NSMakeRect(label_x, 31, icon_size, icon_size)
            )
            # Use "photo" symbol for images
            icon_image = NSImage.imageWithSystemSymbolName_accessibilityDescription_("photo", None)
            if icon_image:
                icon_view.setImage_(icon_image)
                icon_view.setContentTintColor_(NSColor.colorWithWhite_alpha_(0.8, 1.0)) # Match text color
                self.addSubview_(icon_view)
                label_x += icon_size + 8  # Shift text (icon + gap)
                label_width -= (icon_size + 8 + 12) # Account for padding

        # Preview text - Primary
        # Dynamic font size and weight based on length
        text_length = len(self._item.preview)
        is_long = text_length > 60
        
        font_size = 11.0 if is_long else 13.0
        font_weight = 0.0  # Regular
        
        # Determine label frame based on content type
        if self._item.content_type == "image":
            # Single line alignment for "Image" label
            # Center with icon (y=31). Text ~14pt tall.
            # Lowered to 26 to match visual center (cap height) with icon
            label_frame = NSMakeRect(label_x, 26, label_width, 20)
        else:
            # Multi-line paragraph for text items
            # y=26, h=44 as before
            label_frame = NSMakeRect(label_x, 26, label_width, 44)
            
        self._label = NSTextField.alloc().initWithFrame_(label_frame)
        
        # Prepare content with grey ellipsis
        raw_text = self._item.preview
        # Manual truncation to control the ellipsis color
        # 3 lines ~ 130 chars roughly
        display_text = raw_text
        needs_ellipsis = False
        
        if len(raw_text) > 130:
            display_text = raw_text[:130]
            needs_ellipsis = True
        elif raw_text.endswith("..."):
            # Handle existing python truncation
            display_text = raw_text[:-3]
            needs_ellipsis = True
            
        # Create attributed string
        attr_str = NSMutableAttributedString.alloc().initWithString_(display_text)
        
        # Base attributes (Light Grey text, Font)
        font = NSFont.systemFontOfSize_weight_(font_size, font_weight)
        attrs = {
            NSForegroundColorAttributeName: NSColor.colorWithWhite_alpha_(0.8, 1.0), # Light Grey
            NSFontAttributeName: font
        }
        attr_str.addAttributes_range_(attrs, (0, len(display_text)))
        
        if needs_ellipsis:
            ellipsis_str = NSMutableAttributedString.alloc().initWithString_("...")
            ellipsis_attrs = {
                NSForegroundColorAttributeName: NSColor.colorWithWhite_alpha_(0.5, 1.0), # Grey dots
                NSFontAttributeName: font
            }
            ellipsis_str.addAttributes_range_(ellipsis_attrs, (0, 3))
            attr_str.appendAttributedString_(ellipsis_str)
            
        self._label.setAttributedStringValue_(attr_str)
        
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        # setTextColor is ignored when using attributed string, but good for fallback
        self._label.setTextColor_(NSColor.whiteColor())
        # setFont is also overridden by attributes
        
        # Configure for multi-line
        self._label.setMaximumNumberOfLines_(3)
        self._label.cell().setWraps_(True)
        self._label.cell().setLineBreakMode_(0) # NSLineBreakByWordWrapping
        self._label.cell().setTruncatesLastVisibleLine_(True) # Backup truncation
        self.addSubview_(self._label)
        
        # Timestamp - Right aligned
        time_str = self._item.timestamp.strftime("%H:%M")
        self._time_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(label_x, 6, label_width, 16) # Use original label_x/width to align to right edge
        )
        self._time_label.setStringValue_(time_str)
        self._time_label.setAlignment_(NSTextAlignmentRight)  # Right align
        self._time_label.setBezeled_(False)
        self._time_label.setDrawsBackground_(False)
        self._time_label.setEditable_(False)
        self._time_label.setSelectable_(False)
        self._time_label.setTextColor_(NSColor.whiteColor()) # Reverted to white as requested
        self._time_label.setFont_(NSFont.systemFontOfSize_weight_(11, 0.0))
        self.addSubview_(self._time_label)
    
    def _setup_tracking(self):
        """Set up mouse tracking for hover effects."""
        # Add NSTrackingMouseMoved to ensure selection updates even if mouse just moves within the item
        # This allows mouse to "re-take" selection from keyboard
        options = (
            NSTrackingMouseEnteredAndExited |
            NSTrackingMouseMoved |
            NSTrackingActiveAlways |
            NSTrackingInVisibleRect
        )
        tracking = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(), options, self, None
        )
        self.addTrackingArea_(tracking)
    
    def drawRect_(self, rect):
        """Draw the background - Now handled by the floating selection view."""
        # Cleaned up static selection drawing
        pass
    
    def mouseEntered_(self, event):
        """Update selection when mouse enters."""
        if self._on_hover:
            self._on_hover(self._index)

    def mouseMoved_(self, event):
        """Update selection when mouse moves within the item."""
        if self._on_hover:
            self._on_hover(self._index)
    
    def mouseExited_(self, event):
        pass
    
    def mouseDown_(self, event):
        """Handle click on this item."""
        if self._on_click:
            self._on_click(self._index)
    
    def resetCursorRects(self):
        """Set the cursor to a pointing hand when hovering over this item."""
        self.addCursorRect_cursor_(self.bounds(), NSCursor.pointingHandCursor())

    def set_selected(self, selected: bool):
        self._is_selected = selected
        self.setNeedsDisplay_(True)


class ClipboardPopup(NSPanel):
    """
    The main clipboard history popup window.
    A borderless, floating panel with glassmorphism effect.
    """
    
    def _animate_hide(self):
        """Animate the popup hiding using timer."""
        if not self._is_visible:
            return
        self._is_visible = False
        
        # Remove click monitor if exists
        if hasattr(self, '_click_monitor') and self._click_monitor:
            NSEvent.removeMonitor_(self._click_monitor)
            self._click_monitor = None
        
        from AppKit import NSTimer
        
        self._hide_step = 0
        self._hide_steps = 8
        self._hide_start_y = self.frame().origin.y
        self._hide_start_alpha = self.alphaValue()
        
        def step_animation(timer):
            self._hide_step += 1
            progress = self._hide_step / self._hide_steps
            ease = progress * progress
            
            alpha = self._hide_start_alpha * (1 - ease)
            y = self._hide_start_y - (10 * ease)
            
            self.setAlphaValue_(alpha)
            self.setFrameOrigin_(NSMakePoint(self.frame().origin.x, y))
            
            if self._hide_step >= self._hide_steps:
                timer.invalidate()
                self.orderOut_(None)
        
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            0.015, True, step_animation
        )
    
    def _setup_click_outside_monitor(self):
        """Set up a global monitor to detect clicks outside the popup."""
        from AppKit import NSEventMaskLeftMouseDown, NSEventMaskRightMouseDown
        
        def handle_click(event):
            # Check if click is outside our window
            click_location = event.locationInWindow()
            if event.window() != self:
                # Click was outside - dismiss with animation
                print("[Popup] Click outside detected, hiding...", flush=True)
                self._animate_hide()
            return event
        
        self._click_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown,
            handle_click
        )
    
    @classmethod
    def create(cls, on_select: Optional[Callable[[ClipboardItem], None]] = None):
        print("[Popup] Creating panel...", flush=True)
        try:
            # Create borderless panel
            panel = cls.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, POPUP_WIDTH, 100),
                NSWindowStyleMaskBorderless,
                NSBackingStoreBuffered,
                False
            )
            print("[Popup] Panel allocated.", flush=True)
            
            panel._on_select = on_select
            panel._items: List[ClipboardItem] = []
            panel._item_views: List[ClipboardItemView] = []
            panel._selected_index = 0
            panel._is_visible = False
            panel._original_focused_element = None  # Store reference to restore focus
            panel._original_frontmost_app = None  # Store frontmost app to reactivate
            
            # Configure window - use screen saver level to ensure it stays on top of everything
            panel.setLevel_(NSScreenSaverWindowLevel)
            panel.setBackgroundColor_(NSColor.clearColor())  # Transparent background
            panel.setOpaque_(False)
            panel.setHasShadow_(True)
            panel.setHidesOnDeactivate_(False)  # Don't auto-hide when app loses focus
            panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces |
                NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            # Enable mouse moved events to track hover accurately
            panel.setAcceptsMouseMovedEvents_(True)
            
            # Don't set alpha to 0 here - we'll manage it in show()
            print("[Popup] Panel configured.", flush=True)
            
            # Create content with visual effect (blur/glass)
            panel._setup_content_view()
            print("[Popup] Content view created.", flush=True)
            
            return panel
        except Exception as e:
            print(f"[Popup] ERROR creating popup: {e}", flush=True)
            import traceback
            traceback.print_exc()
            raise
    
    def _setup_content_view(self):
        """Set up the glass-effect content view."""
        content_frame = self.contentView().bounds()
        
        # Visual effect view for blur
        self._blur_view = NSVisualEffectView.alloc().initWithFrame_(content_frame)
        # NSVisualEffectMaterial.popover = 6, .dark = 4, .hudWindow = 13
        self._blur_view.setMaterial_(4)  # .dark material for better contrast with white text
        # NSVisualEffectBlendingMode.behindWindow = 0
        self._blur_view.setBlendingMode_(0)
        self._blur_view.setWantsLayer_(True)
        self._blur_view.layer().setCornerRadius_(CORNER_RADIUS)
        self._blur_view.layer().setMasksToBounds_(True)
        self._blur_view.setAutoresizingMask_(18)  # Width + Height flexible
        
        self.contentView().addSubview_(self._blur_view)
        
        # Container for items
        self._items_container = NSView.alloc().initWithFrame_(content_frame)
        self._items_container.setAutoresizingMask_(18)
        self._items_container.setWantsLayer_(True)  # Enable layers for subviews
        self._blur_view.addSubview_(self._items_container)
        
        # Selection Highlight View ("The Ghost")
        # Initialize off-screen, will be positioned/sized in rebuild
        self._selection_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 0))
        self._selection_view.setWantsLayer_(True)
        
        layer = self._selection_view.layer()
        if layer:
            layer.setBackgroundColor_(NSColor.colorWithWhite_alpha_(1.0, 0.15).CGColor())
            layer.setCornerRadius_(6.0)
            layer.setBorderWidth_(1.0)
            layer.setBorderColor_(NSColor.colorWithWhite_alpha_(1.0, 0.1).CGColor())
            
            # Subtle shadow for depth
            layer.setShadowColor_(NSColor.blackColor().CGColor())
            layer.setShadowOpacity_(0.2)
            layer.setShadowOffset_(NSMakePoint(0, -2))
            layer.setShadowRadius_(4)
        
        # Add as first subview so it sits behind items
        self._items_container.addSubview_(self._selection_view)
    
    def update_items(self, items: List[ClipboardItem]):
        """Update the displayed clipboard items."""
        self._items = items[:50]  # Allow up to 50 items (scrollable)
        self._selected_index = 0
        self._rebuild_item_views()
    
    def _rebuild_item_views(self):
        """Rebuild the item views list."""
        from AppKit import NSScrollView, NSClipView
        
        # Clear old views
        for view in self._item_views:
            view.removeFromSuperview()
        self._item_views.clear()
        
        if not self._items:
            return
        
        # Calculate heights - use consistent padding on all sides
        num_items = len(self._items)
        items_height = ITEM_HEIGHT * num_items
        total_content_height = items_height + (PADDING * 2)  # Top and bottom padding
        visible_height = min(total_content_height, POPUP_MAX_HEIGHT)
        
        # Resize window to visible height
        frame = self.frame()
        frame.size.height = visible_height
        self.setFrame_display_(frame, True)
        
        # Resize blur view to fill window
        blur_bounds = self.contentView().bounds()
        self._blur_view.setFrame_(blur_bounds)
        
        # Set up scroll view - use full bounds (corner radius handles clipping)
        if not hasattr(self, '_scroll_view') or self._scroll_view is None:
            from AppKit import NSScrollView
            self._scroll_view = NSScrollView.alloc().initWithFrame_(blur_bounds)
            self._scroll_view.setHasVerticalScroller_(True)
            self._scroll_view.setHasHorizontalScroller_(False)
            self._scroll_view.setAutohidesScrollers_(True)
            self._scroll_view.setDrawsBackground_(False)
            self._scroll_view.setBorderType_(0)  # NSNoBorder
            self._scroll_view.setScrollerStyle_(1)  # NSScrollerStyleOverlay
            self._blur_view.addSubview_(self._scroll_view)
        
        self._scroll_view.setFrame_(blur_bounds)
        
        self._items_container = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, blur_bounds.size.width, total_content_height)
        )
        self._items_container.setWantsLayer_(True) # Enable layer
        self._scroll_view.setDocumentView_(self._items_container)
        
        # Add selection view to the new container
        if hasattr(self, '_selection_view'):
            self._selection_view.removeFromSuperview() # Remove from old parent
            self._items_container.addSubview_(self._selection_view)
            
            # Reset size/position for the first item immediately (no animation)
            if self._items:
                # Same calc as loop below for index 0
                y = total_content_height - PADDING - ITEM_HEIGHT
                start_frame = NSMakeRect(PADDING, y, blur_bounds.size.width - (PADDING * 2), ITEM_HEIGHT)
                self._selection_view.setFrame_(start_frame)
                self._selection_view.setHidden_(False)
            else:
                self._selection_view.setHidden_(True)
        
        # Create item views with consistent padding on all sides
        inner_width = blur_bounds.size.width - (PADDING * 2)  # Left and right padding
        for i, item in enumerate(self._items):
            # Position from top: PADDING + (item_index * ITEM_HEIGHT)
            # In flipped coords: total_height - PADDING - ((i+1) * ITEM_HEIGHT)
            y = total_content_height - PADDING - ((i + 1) * ITEM_HEIGHT)
            view = ClipboardItemView.alloc_with_item(
                item, i, inner_width, 
                on_click=self._on_item_clicked,
                on_hover=self._on_item_hovered
            )
            view.setFrame_(NSMakeRect(PADDING, y, inner_width, ITEM_HEIGHT))
            if i == 0:
                view.set_selected(True)
            self._items_container.addSubview_(view)
            self._item_views.append(view)
        
        # Scroll to top
        if self._items:
            self._scroll_to_item(0)
    
    def show_at_position(self, x: float, y: float, show_above: bool = False):
        """Show the popup at the specified position with animation.
        
        Args:
            x: Center X position for the popup
            y: Y position (bottom-left corner of popup in Cocoa coords)
            show_above: Whether popup is being shown above the input field (affects animation direction)
        """
        # X is centered on element, adjust to get left edge
        actual_x = x - POPUP_WIDTH / 2
        
        # Y is already the correct position from calculate_popup_position
        actual_y = y
        
        # Start position for animation (slightly offset from final)
        if show_above:
            start_y = actual_y + 10  # Animate down from above
        else:
            start_y = actual_y - 10  # Animate up from below
        
        self.setFrameOrigin_(NSMakePoint(actual_x, start_y))
        self.setAlphaValue_(0.0)
        
        # Activate the app first - required for accessory apps to show windows
        app = NSApplication.sharedApplication()
        app.activateIgnoringOtherApps_(True)
        
        # Show window
        self.makeKeyAndOrderFront_(None)
        self.orderFrontRegardless()
        self._is_visible = True
        
        # Set up click outside monitor
        self._setup_click_outside_monitor()
        
        # Animate to final position
        from AppKit import NSAnimationContext
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.15)
        self.animator().setFrameOrigin_(NSMakePoint(actual_x, actual_y))
        self.animator().setAlphaValue_(1.0)
        NSAnimationContext.endGrouping()
    
    def hide(self, refocus: bool = True):
        """Hide the popup with animation."""
        self._animate_hide()
        if refocus:
            self._refocus_original_element()
    
    def move_selection(self, delta: int):
        """Move selection up or down."""
        if not self._item_views:
            return
        
        # Deselect current
        if 0 <= self._selected_index < len(self._item_views):
            self._item_views[self._selected_index].set_selected(False)
        
        # Update index
        self._selected_index = max(0, min(len(self._items) - 1, self._selected_index + delta))
        
        # Select new
        self._item_views[self._selected_index].set_selected(True)
        
        # Animate highlight
        self._animate_selection_change()
        
        # Scroll to make selection visible
        self._scroll_to_item(self._selected_index)
    
    def confirm_selection(self):
        """Confirm the current selection and paste."""
        print(f"[Popup] confirm_selection called, selected_index={self._selected_index}", flush=True)
        
        if not self._items or self._selected_index >= len(self._items):
            print("[Popup] No items or invalid index", flush=True)
            return
        
        item = self._items[self._selected_index]
        print(f"[Popup] Selected item: {item.preview[:30]}...", flush=True)
        
        # Put on clipboard based on content type
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        
        # Handle different content types
        if hasattr(item, 'content_type'):
            if item.content_type == "image" and item.image_data:
                # Write image data (PNG format)
                from AppKit import NSData
                png_data = NSData.dataWithBytes_length_(item.image_data, len(item.image_data))
                pasteboard.setData_forType_(png_data, NSPasteboardTypePNG)
                print("[Popup] Image placed on clipboard", flush=True)
            elif item.content_type == "mixed" and item.image_data and item.text_content:
                # Write both image and text
                from AppKit import NSData
                png_data = NSData.dataWithBytes_length_(item.image_data, len(item.image_data))
                pasteboard.setData_forType_(png_data, NSPasteboardTypePNG)
                pasteboard.setString_forType_(item.text_content, NSPasteboardTypeString)
                print("[Popup] Mixed content placed on clipboard", flush=True)
            else:
                # Text only
                pasteboard.setString_forType_(item.text_content or item.content, NSPasteboardTypeString)
                print("[Popup] Text placed on clipboard", flush=True)
        else:
            # Legacy: just text
            pasteboard.setString_forType_(item.content, NSPasteboardTypeString)
            print("[Popup] Content placed on clipboard", flush=True)
        
        # Hide popup (don't refocus yet, we'll do it after paste)
        self.hide(refocus=False)
        
        # Notify callback
        if self._on_select:
            self._on_select(item)
        
        # Use dispatch_after for non-blocking delayed execution
        # Important: refocus FIRST, then paste, so Cmd+V goes to the right window
        from Foundation import NSTimer
        
        original_element = self._original_focused_element
        original_app = self._original_frontmost_app
        self._original_focused_element = None  # Clear so hide() doesn't refocus again
        self._original_frontmost_app = None
        
        def do_refocus_and_paste(timer):
            # First, activate the original application
            if original_app is not None:
                try:
                    original_app.activateWithOptions_(0)  # 0 = NSApplicationActivateAllWindows
                    print(f"[Popup] Activated app: {original_app.localizedName()}", flush=True)
                except Exception as e:
                    print(f"[Popup] Could not activate app: {e}", flush=True)
            
            # Then refocus the original element
            if original_element is not None:
                try:
                    from ApplicationServices import AXUIElementPerformAction
                    AXUIElementPerformAction(original_element, "AXFocus")
                    print("[Popup] Refocused original element", flush=True)
                except Exception as e:
                    print(f"[Popup] Could not refocus: {e}", flush=True)
            
            # Now paste after a short delay for focus to take effect
            def do_paste(timer2):
                print("[Popup] Executing paste...", flush=True)
                self._simulate_paste()
            
            NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                0.1, False, do_paste
            )
        
        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            0.15, False, do_refocus_and_paste
        )
        
    def _animate_selection_change(self):
        """Animate the selection view to the current selected index."""
        if not self._item_views or self._selected_index >= len(self._item_views):
            return

        target_view = self._item_views[self._selected_index]
        target_frame = target_view.frame()
        
        # Core Animation transaction
        CATransaction.begin()
        CATransaction.setAnimationDuration_(0.4) # Spring takes a bit longer visually
        
        # Spring Animation for position
        # We need to animate the layer's position property
        layer = self._selection_view.layer()
        
        # Get start position from presentation layer (what's currently on screen)
        # This prevents jumps when animating while an animation is already in progress
        presentation = layer.presentationLayer()
        if presentation:
            current_pos = presentation.position()
        else:
            current_pos = layer.position()
        
        # Calculate new position based on anchor point
        # Layer-backed views often use (0,0) anchor, while standalone layers use (0.5, 0.5)
        # We must respect the current anchor to avoid shifting
        anchor = layer.anchorPoint()
        
        new_pos_x = target_frame.origin.x + (target_frame.size.width * anchor.x)
        new_pos_y = target_frame.origin.y + (target_frame.size.height * anchor.y)
        
        spring = CASpringAnimation.animationWithKeyPath_("position")
        spring.setDamping_(12.0)
        spring.setMass_(1.0)
        spring.setStiffness_(150.0)
        spring.setInitialVelocity_(0.0)
        spring.setDuration_(spring.settlingDuration())
        
        spring.setFromValue_(NSValue.valueWithPoint_(current_pos))
        spring.setToValue_(NSValue.valueWithPoint_(NSMakePoint(new_pos_x, new_pos_y)))
        
        # We must set the final value on the model layer immediately so it stays there after animation
        layer.setPosition_(NSMakePoint(new_pos_x, new_pos_y))
        layer.addAnimation_forKey_(spring, "position")
        
        CATransaction.commit()

    def _on_item_clicked(self, index: int):
        """Handle click on a clipboard item."""
        # Update selection state (logical only)
        if 0 <= self._selected_index < len(self._item_views):
            self._item_views[self._selected_index].set_selected(False)
        
        self._selected_index = index
        self._item_views[index].set_selected(True)
        
        # Animate selection highlight
        self._animate_selection_change()
        
        # Confirm the selection
        self.confirm_selection()
    
    def _on_item_hovered(self, index: int):
        """Handle mouse hover on a clipboard item - sync with keyboard selection."""
        if index == self._selected_index:
            return
        
        # Deselect current (logical)
        if 0 <= self._selected_index < len(self._item_views):
            self._item_views[self._selected_index].set_selected(False)
        
        # Select hover (logical)
        self._selected_index = index
        self._item_views[index].set_selected(True)
        
        # Animate selection highlight
        self._animate_selection_change()
    
    def _scroll_to_item(self, index: int):
        """Scroll the scroll view to make the item at index visible."""
        if not hasattr(self, '_scroll_view') or self._scroll_view is None:
            return
        if not self._item_views or index < 0 or index >= len(self._item_views):
            return
        
        item_view = self._item_views[index]
        item_frame = item_view.frame()
        
        # For first item, scroll to absolute top
        if index == 0:
            content_height = self._items_container.frame().size.height
            top_point = NSMakePoint(0, content_height)
            self._items_container.scrollPoint_(top_point)
        else:
            # Scroll to make the item visible
            self._items_container.scrollRectToVisible_(item_frame)
    
    def store_focused_element(self, element):
        """Store the currently focused element to restore later."""
        self._original_focused_element = element
    
    def store_frontmost_app(self, app):
        """Store the frontmost application to reactivate later."""
        self._original_frontmost_app = app
    
    def _refocus_original_element(self):
        """Refocus the original input element."""
        if self._original_focused_element is None:
            return
        
        try:
            from ApplicationServices import AXUIElementPerformAction
            # Try to set focus back to the original element
            AXUIElementPerformAction(self._original_focused_element, "AXFocus")
            print("[Popup] Refocused original element", flush=True)
        except Exception as e:
            print(f"[Popup] Could not refocus original element: {e}", flush=True)
        finally:
            self._original_focused_element = None
    
    def _simulate_paste(self):
        """Simulate Cmd+V keystroke to paste."""
        from Quartz import (
            CGEventCreateKeyboardEvent,
            CGEventSetFlags,
            CGEventPost,
            kCGHIDEventTap,
            kCGEventFlagMaskCommand,
        )
        
        # Key code for V
        KEY_V = 9
        
        # Key down
        event = CGEventCreateKeyboardEvent(None, KEY_V, True)
        CGEventSetFlags(event, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, event)
        
        # Key up
        event = CGEventCreateKeyboardEvent(None, KEY_V, False)
        CGEventSetFlags(event, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, event)
    
    def keyDown_(self, event):
        """Handle keyboard events."""
        key_code = event.keyCode()
        
        # Arrow up
        if key_code == 126:
            self.move_selection(-1)
        # Arrow down
        elif key_code == 125:
            self.move_selection(1)
        # Enter / Return
        elif key_code == 36:
            self.confirm_selection()
        # Escape
        elif key_code == 53:
            self.hide()
        else:
            # Don't call super() - just pass for unhandled keys
            pass
    
    def canBecomeKeyWindow(self):
        return True
    
    def canBecomeMainWindow(self):
        return False
    
    def resignKeyWindow(self):
        """Called when the window loses key status (e.g., user clicks another window)."""
        super().resignKeyWindow()
        if self._is_visible:
            print("[Popup] Lost key window status, hiding with animation...", flush=True)
            self._animate_hide()


def calculate_popup_position(element_rect: ElementRect, popup_height: float) -> tuple:
    """
    Calculate where to show the popup based on the focused element.
    
    The popup should appear directly below the input field unless there's 
    not enough space, in which case it appears directly above.
    
    Args:
        element_rect: The screen coordinates of the focused element (Y from User Top-Left)
        popup_height: The height of the popup window
        
    Returns:
        (x, y, show_above) where x,y is the BOTTOM-LEFT corner of popup in Cocoa coords.
    """
    screens = NSScreen.screens()
    if not screens:
        return (100, 100, False)
        
    # 1. Coordinate System Conversion
    # Cocoa uses a coordinate system where (0,0) is the BOTTOM-LEFT of the PRIMARY screen.
    # Accessibility API (AX) uses (0,0) as the TOP-LEFT of the PRIMARY screen.
    # To convert AX Y to Cocoa Y: CocoaY = PrimaryScreenHeight - AXY
    
    primary_screen = screens[0]
    primary_height = primary_screen.frame().size.height
    
    # Calculate element bounds in Cocoa coordinates
    # AX Y is top of element. width/height are standard.
    # Cocoa Y of element TOP = PrimaryHeight - AX_Y
    # Cocoa Y of element BOTTOM = PrimaryHeight - (AX_Y + Height)
    
    elem_top_cocoa = primary_height - element_rect.y
    elem_bottom_cocoa = primary_height - (element_rect.y + element_rect.height)
    
    elem_x_cocoa = element_rect.x  # X is same
    elem_center_x = element_rect.center_x
    
    print(f"[Pos] Element (AX): y={element_rect.y}, h={element_rect.height} -> Cocoa: top={elem_top_cocoa}, bottom={elem_bottom_cocoa}", flush=True)

    # 2. Find which screen the element is on
    target_screen = primary_screen
    best_overlap = 0.0
    
    # Simple check: find screen containing center point
    # Note: NSScreen frames are in Cocoa coordinates
    for screen in screens:
        # Use visibleFrame to respect Dock and Menu Bar
        frame = screen.visibleFrame()
        # Check if element's center x is within screen width, and element's bottom y within height
        if (frame.origin.x <= elem_center_x <= frame.origin.x + frame.size.width) and \
           (frame.origin.y <= elem_bottom_cocoa <= frame.origin.y + frame.size.height):
            target_screen = screen
            break
            
    screen_frame = target_screen.visibleFrame()
    screen_min_y = screen_frame.origin.y
    screen_max_y = screen_frame.origin.y + screen_frame.size.height
    print(f"[Pos] Target Screen Frame (Visible): {screen_frame}", flush=True)

    # 3. Determine Position
    gap = 6
    
    # Proposal 1: Below the element
    # The popup's top edge should be at (elem_bottom_cocoa - gap)
    # Since popup position defines its BOTTOM-LEFT, we need:
    # y = (elem_bottom_cocoa - gap) - popup_height
    y_below = (elem_bottom_cocoa - gap) - popup_height
    
    # Proposal 2: Above the element
    # The popup's bottom edge should be at (elem_top_cocoa + gap)
    y_above = elem_top_cocoa + gap
    
    # 4. Constraints
    # Check if 'below' fits on screen (bottom edge >= screen_bottom)
    fits_below = y_below >= screen_min_y
    
    # Check if 'above' fits on screen (top edge <= screen_top)
    fits_above = (y_above + popup_height) <= screen_max_y
    
    show_above = False
    final_y = y_below
    
    if fits_below:
        final_y = y_below
        show_above = False
        print("[Pos] Fits below.", flush=True)
    elif fits_above:
        final_y = y_above
        show_above = True
        print("[Pos] Fits above (below blocked).", flush=True)
    else:
        # Fits neither? Pick whichever has more space or clamp to screen
        space_below = elem_bottom_cocoa - screen_min_y
        space_above = screen_max_y - elem_top_cocoa
        
        if space_above > space_below:
             final_y = y_above
             show_above = True
             # Clamp to top
             if final_y + popup_height > screen_max_y:
                 final_y = screen_max_y - popup_height
        else:
             final_y = y_below
             show_above = False
             # Clamp to bottom
             if final_y < screen_min_y:
                 final_y = screen_min_y

    print(f"[Pos] Result: y={final_y}, above={show_above}", flush=True)
    return (elem_center_x, final_y, show_above)
