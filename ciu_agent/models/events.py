"""Spatial events emitted by the Brush Controller.

A SpatialEvent records something that happened at a specific screen
position and time — the cursor entering a zone, clicking, typing, or
losing track of its location entirely. The Director consumes these
events to decide the next action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SpatialEventType(Enum):
    """Classification of spatial events the Brush can emit.

    Attributes:
        ZONE_ENTER: Cursor moved into a zone's bounds.
        ZONE_EXIT: Cursor moved out of a zone's bounds.
        ZONE_HOVER: Cursor is dwelling inside a zone.
        ZONE_CLICK: A click was performed on a zone.
        ZONE_TYPE: Text was typed while a zone was focused.
        BRUSH_LOST: The cursor position could not be determined.
    """

    ZONE_ENTER = "zone_enter"
    ZONE_EXIT = "zone_exit"
    ZONE_HOVER = "zone_hover"
    ZONE_CLICK = "zone_click"
    ZONE_TYPE = "zone_type"
    BRUSH_LOST = "brush_lost"


@dataclass
class SpatialEvent:
    """A single spatial event captured at a moment in time.

    Every event is tied to a screen position and (optionally) a zone.
    The ``data`` dict carries event-specific payload — for example a
    ``ZONE_CLICK`` may include ``{"button": "left"}`` and a
    ``ZONE_TYPE`` may include ``{"text": "hello"}``.

    Attributes:
        type: The kind of spatial event.
        zone_id: Identifier of the zone involved, or an empty string
            for ``BRUSH_LOST`` events where no zone is relevant.
        timestamp: Unix timestamp when the event occurred.
        position: Screen coordinates ``(x, y)`` of the cursor at the
            time of the event.
        data: Optional event-specific payload. Common keys include:

            * ``button`` (str): Mouse button for click events
              (``"left"``, ``"right"``, ``"middle"``).
            * ``text`` (str): Typed text for ``ZONE_TYPE`` events.
            * ``duration`` (float): Hover duration in seconds.
            * ``expected_zone`` (str): Zone id the Brush expected to
              be over (useful for diagnostics when zones shift).
    """

    type: SpatialEventType
    zone_id: str
    timestamp: float
    position: tuple[int, int]
    data: dict[str, Any] = field(default_factory=dict)
