"""
Accessibility Helper - Gets focused element position using macOS Accessibility API.
"""

from typing import Optional, Tuple
from dataclasses import dataclass

from ApplicationServices import (
    AXUIElementCreateSystemWide,
    AXUIElementCopyAttributeValue,
    kAXErrorSuccess,
    kAXFocusedUIElementAttribute,
    kAXPositionAttribute,
    kAXSizeAttribute,
    AXIsProcessTrusted,
)
from AppKit import NSScreen


@dataclass
class ElementRect:
    """Rectangle representing a UI element's position and size."""
    x: float
    y: float
    width: float
    height: float
    
    @property
    def bottom(self) -> float:
        """Bottom edge Y coordinate (in screen coordinates, Y goes down)."""
        return self.y + self.height
    
    @property
    def center_x(self) -> float:
        """Horizontal center of the element."""
        return self.x + self.width / 2


def extract_point_from_axvalue(value) -> Optional[Tuple[float, float]]:
    """Extract x, y coordinates from an AXValue representing a point."""
    try:
        # The value is typically a wrapped AXValue - try to get the description
        # and parse it, as direct access varies by PyObjC version
        desc = str(value)
        
        # AXValue descriptions look like: "x:123.0 y:456.0"
        if 'x:' in desc and 'y:' in desc:
            import re
            match = re.search(r'x:\s*([-\d.]+).*y:\s*([-\d.]+)', desc)
            if match:
                return (float(match.group(1)), float(match.group(2)))
        
        # Try direct attribute access (some PyObjC versions)
        if hasattr(value, 'x') and hasattr(value, 'y'):
            return (float(value.x), float(value.y))
        
        return None
    except Exception as e:
        print(f"[Accessibility] Error extracting point: {e}")
        return None


def extract_size_from_axvalue(value) -> Optional[Tuple[float, float]]:
    """Extract width, height from an AXValue representing a size."""
    try:
        desc = str(value)
        
        # AXValue descriptions look like: "w:123.0 h:456.0"
        if 'w:' in desc and 'h:' in desc:
            import re
            match = re.search(r'w:\s*([-\d.]+).*h:\s*([-\d.]+)', desc)
            if match:
                return (float(match.group(1)), float(match.group(2)))
        
        # Try direct attribute access
        if hasattr(value, 'width') and hasattr(value, 'height'):
            return (float(value.width), float(value.height))
        
        return None
    except Exception as e:
        print(f"[Accessibility] Error extracting size: {e}")
        return None


class AccessibilityHelper:
    """
    Helper class for macOS Accessibility API operations.
    Gets the position of the currently focused UI element.
    """
    
    def __init__(self):
        self._system_wide = AXUIElementCreateSystemWide()
    
    def get_focused_element_rect(self) -> Optional[ElementRect]:
        """
        Get the rectangle of the currently focused UI element.
        Returns None if no element is focused or data unavailable.
        """
        try:
            # Get focused element
            focused_element = self._get_focused_element()
            if focused_element is None:
                print("[Accessibility] No focused element found")
                return None
            
            # Get position
            position = self._get_element_position(focused_element)
            if position is None:
                print("[Accessibility] Could not get element position")
                return None
            
            # Get size
            size = self._get_element_size(focused_element)
            if size is None:
                size = (100, 22)  # Default size
            
            print(f"[Accessibility] Element rect: pos={position}, size={size}")
            return ElementRect(
                x=position[0],
                y=position[1],
                width=size[0],
                height=size[1]
            )
        except Exception as e:
            print(f"[Accessibility] Error getting element rect: {e}")
            return None
    
    def get_focused_element(self):
        """Get the currently focused UI element. Can be used for refocusing later."""
        error, focused_element = AXUIElementCopyAttributeValue(
            self._system_wide,
            kAXFocusedUIElementAttribute,
            None
        )
        
        if error != kAXErrorSuccess:
            return None
        
        return focused_element
    
    # Alias for internal use
    def _get_focused_element(self):
        return self.get_focused_element()
    
    def _get_element_position(self, element) -> Optional[Tuple[float, float]]:
        """Get the position of an accessibility element."""
        error, position_value = AXUIElementCopyAttributeValue(
            element,
            kAXPositionAttribute,
            None
        )
        
        if error != kAXErrorSuccess or position_value is None:
            return None
        
        return extract_point_from_axvalue(position_value)
    
    def _get_element_size(self, element) -> Optional[Tuple[float, float]]:
        """Get the size of an accessibility element."""
        error, size_value = AXUIElementCopyAttributeValue(
            element,
            kAXSizeAttribute,
            None
        )
        
        if error != kAXErrorSuccess or size_value is None:
            return None
        
        return extract_size_from_axvalue(size_value)
    
    @staticmethod
    def get_screen_height() -> float:
        """Get the main screen height."""
        screen = NSScreen.mainScreen()
        if screen:
            return screen.frame().size.height
        return 900
    
    @staticmethod
    def check_accessibility_permission() -> bool:
        """Check if accessibility permission is granted."""
        return AXIsProcessTrusted()
