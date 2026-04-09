from AppKit import (
    NSAnimationContext,
    NSTimer,
    NSMakePoint,
    NSMakeRect,
    NSEvent,
    NSView,
    NSColor
)
from Quartz import (
    CAMediaTimingFunction,
    kCAMediaTimingFunctionEaseOut
)
import traceback
from typing import List, Optional

from .constants import (
    PADDING, 
    ITEM_HEIGHT, 
    EDIT_BUTTON_HEIGHT, 
    POPUP_MAX_HEIGHT,
    POPUP_WIDTH,
    SEARCH_BAR_HEIGHT,
)

class PopupAnimationMixin:
    """
    Mixin for ClipboardPopup to handle animations.
    Expected to be mixed into a class that inherits from NSPanel/NSWindow and has specific attributes.
    """
    
    def _init_deletion_queue(self):
        """Initialize the deletion queue system."""
        if not hasattr(self, '_deletion_queue'):
            self._deletion_queue = []  # List of pending deletion requests
            self._deletion_in_progress = False  # True if an animation is currently running
            self._pending_deletion_views = set()  # Track views already queued for deletion
    
    def _queue_item_deletion(self, view_index: int, on_delete_callback=None, item_index: int = None):
        """Queue a complete deletion operation. Processes immediately if no animation is running.
        
        view_index: The index into _item_views at the time of queueing.
        on_delete_callback: Optional callback to call when processing (e.g., to notify main.py)
        item_index: The original item index for the callback
        """
        self._init_deletion_queue()
        
        # Check if this view is already pending deletion - prevent double-delete
        if view_index in self._pending_deletion_views:
            print(f"[Popup] View {view_index} already pending deletion, ignoring", flush=True)
            return
        
        # Mark as pending
        self._pending_deletion_views.add(view_index)
        
        # Add to queue with all necessary info
        self._deletion_queue.append({
            'view_index': view_index,
            'on_delete_callback': on_delete_callback,
            'item_index': item_index
        })
        print(f"[Popup] Queued deletion for view index {view_index}, queue size: {len(self._deletion_queue)}", flush=True)
        
        # If no animation is running, start processing
        if not self._deletion_in_progress:
            self._process_deletion_queue()
    
    def _process_deletion_queue(self):
        """Process the next item in the deletion queue."""
        self._init_deletion_queue()
        
        if not self._deletion_queue:
            print(f"[Popup] Deletion queue empty, done processing", flush=True)
            return
        
        if self._deletion_in_progress:
            print(f"[Popup] Deletion already in progress, waiting...", flush=True)
            return
        
        # Pop the next deletion request
        request = self._deletion_queue.pop(0)
        view_index = request['view_index']
        
        # Validate the index is still valid
        if view_index >= len(self._item_views):
            print(f"[Popup] View index {view_index} out of bounds (len={len(self._item_views)}), skipping", flush=True)
            # Remove from pending set
            self._pending_deletion_views.discard(view_index)
            self._process_deletion_queue()
            return
        
        self._deletion_in_progress = True
        print(f"[Popup] Processing deletion at view index {view_index}, remaining in queue: {len(self._deletion_queue)}", flush=True)
        
        # Call the delete callback to notify main.py BEFORE modifying data
        # Use the current view_index since data hasn't been modified yet
        if request['on_delete_callback']:
            request['on_delete_callback'](view_index)
        
        # Remove from items list NOW (data deletion happens here, in sequence)
        if view_index < len(self._items):
            del self._items[view_index]
        
        # Adjust all remaining queued indices - items after this one shift down by 1
        for i in range(len(self._deletion_queue)):
            if self._deletion_queue[i]['view_index'] > view_index:
                self._deletion_queue[i]['view_index'] -= 1
        
        # Also adjust the pending set
        new_pending = set()
        for pending_idx in self._pending_deletion_views:
            if pending_idx == view_index:
                continue  # This one is being processed now
            elif pending_idx > view_index:
                new_pending.add(pending_idx - 1)
            else:
                new_pending.add(pending_idx)
        self._pending_deletion_views = new_pending
        
        # Trigger the actual animation
        self._animate_item_removal_queued(view_index)
    
    def _animate_hide(self):
        """Animate the popup hiding using timer."""
        if not self._is_visible:
            return
        self._is_visible = False
        
        # Remove click monitor if exists
        if hasattr(self, '_click_monitor') and self._click_monitor:
            NSEvent.removeMonitor_(self._click_monitor)
            self._click_monitor = None
        
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

    def _animate_selection_change(self):
        """Animate the selection view to the current selected index."""
        target_frame = None
        
        # Determine target frame
        if self._selected_index == 0:
            if self._edit_button_view:
                target_frame = self._edit_button_view.frame()
        elif 1 <= self._selected_index <= len(self._item_views):
            view = self._item_views[self._selected_index - 1]
            target_frame = view.frame()
            
        if target_frame is None:
            self._selection_view.setHidden_(True)
            return
            
        self._selection_view.setHidden_(False)
        
        # Use NSAnimationContext for fluid frame animation (position + size)
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.15)
        # Use easeOut for gliding effect
        NSAnimationContext.currentContext().setTimingFunction_(
            CAMediaTimingFunction.functionWithName_(kCAMediaTimingFunctionEaseOut)
        )
        
        self._selection_view.animator().setFrame_(target_frame)
        
        NSAnimationContext.endGrouping()

    def _animate_item_removal(self, removed_index: int):
        """Animate removal of an item and repositioning of remaining items.
        This is called directly for the old API. For queue-based deletion, use _queue_item_deletion."""
        self._init_deletion_queue()
        
        # If using the direct API, just run the animation directly
        self._deletion_in_progress = True
        self._animate_item_removal_queued(removed_index)
    
    def _animate_item_removal_queued(self, removed_index: int):
        """Internal: Animate removal of an item (called from queue processor)."""
        
        print(f"[Popup] _animate_item_removal_queued called, removed_index={removed_index}, item_views={len(self._item_views)}", flush=True)
        
        if removed_index >= len(self._item_views):
            print(f"[Popup] removed_index out of bounds, skipping animation", flush=True)
            return
        
        try:
            removed_view = self._item_views[removed_index]
            
            # Calculate new dimensions (for after the animation)
            num_items = len(self._items)
            search_bar_space = SEARCH_BAR_HEIGHT + PADDING
            items_height = ITEM_HEIGHT * num_items
            new_total_content_height = items_height + search_bar_space + (PADDING * 3)
            new_visible_height = min(new_total_content_height, POPUP_MAX_HEIGHT)
            
            # Store current values for the closure
            blur_width = self.contentView().bounds().size.width
            old_selected_index = self._selected_index
            
            # Figure out new selection - stay at same position if possible
            if num_items == 0:
                new_selected_index = 0  # Edit button only
            elif old_selected_index - 1 >= num_items:
                new_selected_index = num_items  # Last remaining item (1-indexed)
            else:
                new_selected_index = old_selected_index
            
            # Animation parameters
            duration = 0.2
            
            # Calculate window height change (delta)
            # This is positive if window shrinks (bottom moves up)
            frame = self.frame()
            old_height = frame.size.height
            height_delta = old_height - new_visible_height
            
            # If we are deleting the LAST item (num_items == 0), just fade out the whole window
            if num_items == 0:
                print(f"[Popup] Deleting last item, dismissing window", flush=True)
                self.hide(animate=True)
                
                # Capture popup reference for closure
                popup = self
                
                # Cleanup state in background after window fades
                def cleanup_last_item(timer):
                    removed_view.removeFromSuperview()
                    if removed_index < len(popup._item_views):
                        popup._item_views.pop(removed_index)
                    popup._items_container.setFrame_(NSMakeRect(0, 0, blur_width, 0))
                    popup._selected_index = 0
                    if popup._edit_button_view:
                        popup._edit_button_view.set_selected(True) # Reset to edit button
                    
                    # Clear the deletion queue and mark complete since window is hidden
                    popup._deletion_in_progress = False
                    popup._deletion_queue = []
                    popup._pending_deletion_views = set()
                        
                NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                    0.25, False, cleanup_last_item
                )
                return

            # Generalized Animation Logic:
            NSAnimationContext.beginGrouping()
            NSAnimationContext.currentContext().setDuration_(duration)
            
            # 1. Fade out the removed item
            removed_view.animator().setAlphaValue_(0.0)
            
            # 2. Animate items ABOVE (index < removed_index) -> Move Down by delta
            for i in range(removed_index):
                view = self._item_views[i]
                current_frame = view.frame()
                new_y = current_frame.origin.y - height_delta
                view.animator().setFrameOrigin_(NSMakePoint(current_frame.origin.x, new_y))
            
            # 3. Animate Edit Button -> Move Down by delta
            if self._edit_button_view:
                current_frame = self._edit_button_view.frame()
                new_y = current_frame.origin.y - height_delta
                self._edit_button_view.animator().setFrameOrigin_(NSMakePoint(current_frame.origin.x, new_y))

            # 4. Animate items BELOW (index > removed_index) -> Move Up by (ITEM_HEIGHT - delta)
            offset_below = ITEM_HEIGHT - height_delta
            for i in range(removed_index + 1, len(self._item_views)):
                view = self._item_views[i]
                current_frame = view.frame()
                new_y = current_frame.origin.y + offset_below
                view.animator().setFrameOrigin_(NSMakePoint(current_frame.origin.x, new_y))
            
            # 5. Animate Selection View
            if new_selected_index > 0 and new_selected_index - 1 < len(self._item_views):
                target_index = new_selected_index - 1
                
                if target_index < removed_index:
                    target_view = self._item_views[target_index]
                    current_frame = target_view.frame()
                    new_y = current_frame.origin.y - height_delta
                    
                elif target_index > removed_index:
                    target_view = self._item_views[target_index]
                    current_frame = target_view.frame()
                    offset_below = ITEM_HEIGHT - height_delta
                    new_y = current_frame.origin.y + offset_below
                    
                else: 
                    current_frame = removed_view.frame()
                    new_y = current_frame.origin.y - height_delta
                
                sel_frame = NSMakeRect(PADDING, new_y, blur_width - (PADDING * 2), ITEM_HEIGHT)
                self._selection_view.animator().setFrame_(sel_frame)
                
            elif new_selected_index == 0 and self._edit_button_view:
                current_frame = self._edit_button_view.frame()
                new_y = current_frame.origin.y - height_delta
                new_edit_frame = NSMakeRect(current_frame.origin.x, new_y, current_frame.size.width, current_frame.size.height)
                self._selection_view.animator().setFrame_(new_edit_frame)
            
            # 6. Animate Window Resize
            if height_delta != 0:
                frame.size.height = new_visible_height
                frame.origin.y += height_delta
                self.animator().setFrame_display_(frame, True)
            
            NSAnimationContext.endGrouping()
            
            # Capture values for the closure
            popup = self
            
            # After animation completes, update container and window size
            def cleanup_after_animation(timer):
                try:
                    print(f"[Popup] cleanup_after_animation running", flush=True)
                    
                    # Remove the deleted view
                    removed_view.removeFromSuperview()
                    if removed_index < len(popup._item_views):
                        popup._item_views.pop(removed_index)
                    
                    # Update indices for remaining views
                    for i, view in enumerate(popup._item_views):
                        view._index = i + 1  # 1-based index
                    
                    # Resize container and edit button to match new content
                    popup._items_container.setFrame_(NSMakeRect(0, 0, blur_width, new_total_content_height))
                    
                    # Reposition edit button
                    if popup._edit_button_view:
                        search_y = new_total_content_height - PADDING - SEARCH_BAR_HEIGHT
                        edit_btn_x = blur_width - PADDING - 64
                        edit_btn_y = search_y + (SEARCH_BAR_HEIGHT - EDIT_BUTTON_HEIGHT) / 2
                        popup._edit_button_view.setFrameOrigin_(NSMakePoint(edit_btn_x, edit_btn_y))
                    
                    # Reposition all items to their final correct positions
                    for i, view in enumerate(popup._item_views):
                        y = new_total_content_height - PADDING - search_bar_space - ((i + 1) * ITEM_HEIGHT)
                        view.setFrameOrigin_(NSMakePoint(PADDING, y))
                    
                    # Update selection
                    popup._selected_index = new_selected_index
                    
                    # Deselect all first
                    for view in popup._item_views:
                        view.set_selected(False)
                    if popup._edit_button_view:
                        popup._edit_button_view.set_selected(False)
                    
                    # Select the new item
                    if new_selected_index == 0:
                        if popup._edit_button_view:
                            popup._edit_button_view.set_selected(True)
                        popup._selection_view.setHidden_(True)
                    elif new_selected_index - 1 < len(popup._item_views):
                        popup._item_views[new_selected_index - 1].set_selected(True)
                        popup._selection_view.setHidden_(False)
                        # Update selection view to correct position
                        target_view = popup._item_views[new_selected_index - 1]
                        popup._selection_view.setFrame_(target_view.frame())
                    
                    print(f"[Popup] cleanup_after_animation completed, new_selected={new_selected_index}", flush=True)
                except Exception as e:
                    print(f"[Popup] Error in cleanup_after_animation: {e}", flush=True)
                    traceback.print_exc()
            
            def on_animation_complete(timer):
                cleanup_after_animation(timer)
                # Mark deletion as complete and process next in queue
                popup._deletion_in_progress = False
                popup._process_deletion_queue()
            
            NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                duration + 0.05, False, on_animation_complete
            )
        except Exception as e:
            print(f"[Popup] Error in _animate_item_removal: {e}", flush=True)
            traceback.print_exc()
