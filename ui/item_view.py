"""
ClipboardItemView - A single clipboard item row in the popup.
"""

from typing import Callable, Optional

from AppKit import (
    NSView,
    NSTextField,
    NSColor,
    NSFont,
    NSCursor,
    NSTrackingArea,
    NSTrackingMouseEnteredAndExited,
    NSTrackingMouseMoved,
    NSTrackingActiveAlways,
    NSTrackingInVisibleRect,
    NSMakeRect,
)

from clipboard_monitor import ClipboardItem
from .constants import ITEM_HEIGHT, PADDING, DELETE_BUTTON_SIZE


class ClipboardItemView(NSView):
    """A single clipboard item row in the popup."""
    
    @classmethod
    def alloc_with_item(cls, item: ClipboardItem, index: int, width: float, 
                        on_click: Optional[Callable[[int], None]] = None,
                        on_hover: Optional[Callable[[int], None]] = None,
                        on_delete: Optional[Callable[[int], None]] = None):
        view = cls.alloc().initWithFrame_(NSMakeRect(0, 0, width, ITEM_HEIGHT))
        view._item = item
        view._index = index
        view._is_selected = False
        view._is_edit_mode = False
        view._on_click = on_click
        view._on_hover = on_hover
        view._on_delete = on_delete
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
            label_x += 12
            
            icon_size = 14
            icon_view = NSImageView.alloc().initWithFrame_(
                NSMakeRect(label_x, 31, icon_size, icon_size)
            )
            # Use "photo" symbol for images
            icon_image = NSImage.imageWithSystemSymbolName_accessibilityDescription_("photo", None)
            if icon_image:
                icon_view.setImage_(icon_image)
                icon_view.setContentTintColor_(NSColor.colorWithWhite_alpha_(0.8, 1.0))
                self.addSubview_(icon_view)
                label_x += icon_size + 8
                label_width -= (icon_size + 8 + 12)

        # Preview text - Primary
        text_length = len(self._item.preview)
        is_long = text_length > 60
        
        font_size = 11.0 if is_long else 13.0
        font_weight = 0.0  # Regular
        
        # Determine label frame based on content type
        if self._item.content_type == "image":
            label_frame = NSMakeRect(label_x, 26, label_width, 20)
        else:
            label_frame = NSMakeRect(label_x, 26, label_width, 44)
            
        self._label = NSTextField.alloc().initWithFrame_(label_frame)
        
        # Prepare content with grey ellipsis
        raw_text = self._item.preview
        display_text = raw_text
        needs_ellipsis = False
        
        if len(raw_text) > 130:
            display_text = raw_text[:130]
            needs_ellipsis = True
        elif raw_text.endswith("..."):
            display_text = raw_text[:-3]
            needs_ellipsis = True
            
        # Create attributed string
        attr_str = NSMutableAttributedString.alloc().initWithString_(display_text)
        
        # Base attributes
        font = NSFont.systemFontOfSize_weight_(font_size, font_weight)
        attrs = {
            NSForegroundColorAttributeName: NSColor.colorWithWhite_alpha_(0.8, 1.0),
            NSFontAttributeName: font
        }
        attr_str.addAttributes_range_(attrs, (0, len(display_text)))
        
        if needs_ellipsis:
            ellipsis_str = NSMutableAttributedString.alloc().initWithString_("...")
            ellipsis_attrs = {
                NSForegroundColorAttributeName: NSColor.colorWithWhite_alpha_(0.5, 1.0),
                NSFontAttributeName: font
            }
            ellipsis_str.addAttributes_range_(ellipsis_attrs, (0, 3))
            attr_str.appendAttributedString_(ellipsis_str)
            
        self._label.setAttributedStringValue_(attr_str)
        
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setTextColor_(NSColor.whiteColor())
        
        # Configure for multi-line
        self._label.setMaximumNumberOfLines_(3)
        self._label.cell().setWraps_(True)
        self._label.cell().setLineBreakMode_(0)  # NSLineBreakByWordWrapping
        self._label.cell().setTruncatesLastVisibleLine_(True)
        self.addSubview_(self._label)
        
        # Number badge in bottom-left
        item_number = self._index  # _index is 1-based (edit button is 0)
        if 1 <= item_number <= 8:
            badge_w = 18
            badge_h = 18
            badge_x = PADDING
            badge_y = 6
            
            self._badge_bg = NSView.alloc().initWithFrame_(
                NSMakeRect(badge_x, badge_y, badge_w, badge_h)
            )
            self._badge_bg.setWantsLayer_(True)
            badge_layer = self._badge_bg.layer()
            if badge_layer:
                badge_layer.setCornerRadius_(5)
                badge_layer.setBackgroundColor_(
                    NSColor.colorWithWhite_alpha_(1.0, 0.10).CGColor()
                )
                badge_layer.setBorderWidth_(0.5)
                badge_layer.setBorderColor_(
                    NSColor.colorWithWhite_alpha_(1.0, 0.08).CGColor()
                )
            self.addSubview_(self._badge_bg)
            
            self._badge_label = NSTextField.alloc().initWithFrame_(
                NSMakeRect(badge_x, badge_y - 2, badge_w, badge_h)
            )
            self._badge_label.setStringValue_(str(item_number))
            from AppKit import NSTextAlignmentCenter
            self._badge_label.setAlignment_(NSTextAlignmentCenter)
            self._badge_label.setBezeled_(False)
            self._badge_label.setDrawsBackground_(False)
            self._badge_label.setEditable_(False)
            self._badge_label.setSelectable_(False)
            self._badge_label.setTextColor_(NSColor.colorWithWhite_alpha_(0.55, 1.0))
            self._badge_label.setFont_(NSFont.monospacedSystemFontOfSize_weight_(10, 0.3))
            self.addSubview_(self._badge_label)
        
        # Timestamp - Right aligned
        time_str = self._item.timestamp.strftime("%H:%M")
        self._time_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(label_x, 6, label_width, 16)
        )
        self._time_label.setStringValue_(time_str)
        self._time_label.setAlignment_(NSTextAlignmentRight)
        self._time_label.setBezeled_(False)
        self._time_label.setDrawsBackground_(False)
        self._time_label.setEditable_(False)
        self._time_label.setSelectable_(False)
        self._time_label.setTextColor_(NSColor.whiteColor())
        self._time_label.setFont_(NSFont.systemFontOfSize_weight_(11, 0.0))
        self._time_label.setWantsLayer_(True)
        self.addSubview_(self._time_label)
        
        # Delete button (hidden by default, shown in edit mode)
        del_size = 20
        delete_btn_y = 6
        delete_btn_x = self.frame().size.width - PADDING - del_size
        
        self._delete_button = NSView.alloc().initWithFrame_(
            NSMakeRect(delete_btn_x, delete_btn_y, del_size, del_size)
        )
        self._delete_button.setWantsLayer_(True)
        self._delete_button.layer().setCornerRadius_(del_size / 2)
        self._delete_button.layer().setBackgroundColor_(
            NSColor.colorWithRed_green_blue_alpha_(0.9, 0.3, 0.3, 0.4).CGColor()
        )
        
        # Trash icon
        icon_inset = 5
        trash_icon = NSImageView.alloc().initWithFrame_(
            NSMakeRect(icon_inset, icon_inset, del_size - (icon_inset * 2), del_size - (icon_inset * 2))
        )
        trash_image = NSImage.imageWithSystemSymbolName_accessibilityDescription_("trash", None)
        if trash_image:
            trash_icon.setImage_(trash_image)
            trash_icon.setContentTintColor_(NSColor.whiteColor())
        self._delete_button.addSubview_(trash_icon)
        self._delete_button.setAlphaValue_(0.0)
        self._delete_button.setHidden_(False)
        self.addSubview_(self._delete_button)
    
    def _setup_tracking(self):
        """Set up mouse tracking for hover effects."""
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
        """Draw the background - handled by the floating selection view."""
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
    
    def set_edit_mode(self, enabled: bool):
        """Toggle between showing timestamp and delete button."""
        self._is_edit_mode = enabled
        
        from AppKit import NSAnimationContext
        
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.2)
        
        if enabled:
            self._time_label.animator().setAlphaValue_(0.0)
            self._delete_button.animator().setAlphaValue_(1.0)
        else:
            self._time_label.animator().setAlphaValue_(1.0)
            self._delete_button.animator().setAlphaValue_(0.0)
            
        NSAnimationContext.endGrouping()
    
    def _handle_delete_click(self):
        """Handle click on delete button."""
        if self._on_delete:
            self._on_delete(self._index)
