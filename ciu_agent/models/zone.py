"""Zone model: bounded rectangular screen regions with interactive meaning.

A Zone represents a UI element detected on screen — a button, text field,
checkbox, or any other region the Brush Controller may interact with.
Each zone carries its type, current state, spatial bounds, and a
confidence score from the detection layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ZoneType(Enum):
    """Classification of a screen zone by its UI role.

    Attributes:
        BUTTON: A clickable button element.
        TEXT_FIELD: An editable text input area.
        LINK: A navigational hyperlink.
        DROPDOWN: A collapsible selection menu.
        CHECKBOX: A togglable check box.
        SLIDER: A draggable range control.
        MENU_ITEM: An individual entry inside a menu.
        TAB: A tab selector in a tab bar.
        SCROLL_AREA: A region that supports scrolling.
        STATIC: A non-interactive display element.
        UNKNOWN: Zone type could not be determined.
    """

    BUTTON = "button"
    TEXT_FIELD = "text_field"
    LINK = "link"
    DROPDOWN = "dropdown"
    CHECKBOX = "checkbox"
    SLIDER = "slider"
    MENU_ITEM = "menu_item"
    TAB = "tab"
    SCROLL_AREA = "scroll_area"
    STATIC = "static"
    UNKNOWN = "unknown"


class ZoneState(Enum):
    """Observable state of a zone at a point in time.

    Attributes:
        ENABLED: Zone accepts interaction.
        DISABLED: Zone is visible but non-interactive.
        FOCUSED: Zone currently holds input focus.
        HOVERED: Cursor is over the zone.
        PRESSED: Zone is being actively pressed.
        CHECKED: Checkbox or toggle is in the on state.
        UNCHECKED: Checkbox or toggle is in the off state.
        EXPANDED: Collapsible element is open.
        COLLAPSED: Collapsible element is closed.
        UNKNOWN: State could not be determined.
    """

    ENABLED = "enabled"
    DISABLED = "disabled"
    FOCUSED = "focused"
    HOVERED = "hovered"
    PRESSED = "pressed"
    CHECKED = "checked"
    UNCHECKED = "unchecked"
    EXPANDED = "expanded"
    COLLAPSED = "collapsed"
    UNKNOWN = "unknown"


@dataclass
class Rectangle:
    """Axis-aligned bounding rectangle in screen coordinates.

    All values are in pixels. The origin (0, 0) is the top-left corner
    of the primary display.

    Attributes:
        x: Left edge x-coordinate.
        y: Top edge y-coordinate.
        width: Horizontal extent in pixels (must be >= 0).
        height: Vertical extent in pixels (must be >= 0).
    """

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        """Validate that width and height are non-negative."""
        if self.width < 0:
            raise ValueError(f"Rectangle width must be >= 0, got {self.width}")
        if self.height < 0:
            raise ValueError(f"Rectangle height must be >= 0, got {self.height}")

    def contains_point(self, px: int, py: int) -> bool:
        """Check whether a point lies inside (or on the edge of) this rect.

        Args:
            px: X-coordinate of the point.
            py: Y-coordinate of the point.

        Returns:
            True if the point is within the rectangle bounds.
        """
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height

    def center(self) -> tuple[int, int]:
        """Return the center point of the rectangle.

        Returns:
            A (cx, cy) tuple of integer pixel coordinates.
        """
        cx = self.x + self.width // 2
        cy = self.y + self.height // 2
        return (cx, cy)

    def overlaps(self, other: Rectangle) -> bool:
        """Check whether this rectangle overlaps with another.

        Two rectangles overlap when their interiors share at least one
        point. Touching edges alone do not count as overlap.

        Args:
            other: The rectangle to test against.

        Returns:
            True if the rectangles overlap.
        """
        if self.area() == 0 or other.area() == 0:
            return False
        if self.x + self.width <= other.x:
            return False
        if other.x + other.width <= self.x:
            return False
        if self.y + self.height <= other.y:
            return False
        if other.y + other.height <= self.y:
            return False
        return True

    def area(self) -> int:
        """Return the area of the rectangle in square pixels.

        Returns:
            The product of width and height.
        """
        return self.width * self.height


@dataclass
class Zone:
    """A bounded screen region with interactive meaning.

    Zones are the primary spatial primitive in CIU Agent. The Canvas
    Mapper discovers zones via frame analysis, and the Brush Controller
    targets them for interaction.

    Attributes:
        id: Unique identifier for this zone (e.g. ``"btn_save_42"``).
        bounds: Pixel-level bounding rectangle on screen.
        type: Classification of the zone's UI role.
        label: Human-readable label (e.g. ``"Save"``).
        state: Current observable state of the zone.
        parent_id: Id of the enclosing zone, or None if top-level.
        confidence: Detection confidence in [0.0, 1.0].
        last_seen: Unix timestamp of the most recent frame where the
            zone was observed.
    """

    id: str
    bounds: Rectangle
    type: ZoneType
    label: str
    state: ZoneState = ZoneState.ENABLED
    parent_id: str | None = None
    confidence: float = 1.0
    last_seen: float = 0.0

    def __post_init__(self) -> None:
        """Validate confidence is within the expected range."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

    def contains_point(self, px: int, py: int) -> bool:
        """Check whether a screen point falls within this zone.

        Delegates to the underlying Rectangle bounds.

        Args:
            px: X-coordinate of the point.
            py: Y-coordinate of the point.

        Returns:
            True if the point is inside the zone bounds.
        """
        return self.bounds.contains_point(px, py)
