"""Actions and trajectories for the Brush Controller.

An Action describes *what* to do (click a button, type text, scroll),
while a Trajectory describes *how* to move the cursor to reach the
target zone before the action executes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(Enum):
    """The kind of input action the Brush can perform.

    Attributes:
        CLICK: A single mouse click.
        DOUBLE_CLICK: Two rapid clicks.
        TYPE_TEXT: Keyboard text entry.
        KEY_PRESS: A single key or key-combo press.
        SCROLL: Mouse wheel or touchpad scroll.
        DRAG: Press-hold-move-release sequence.
        MOVE: Cursor movement without clicking.
    """

    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    TYPE_TEXT = "type_text"
    KEY_PRESS = "key_press"
    SCROLL = "scroll"
    DRAG = "drag"
    MOVE = "move"


class ActionStatus(Enum):
    """Lifecycle status of an action.

    Attributes:
        PENDING: Action has been created but not yet started.
        IN_PROGRESS: Action is currently being executed.
        COMPLETED: Action finished successfully.
        FAILED: Action could not be completed.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Action:
    """A discrete input action directed at a screen zone.

    The ``parameters`` dict carries action-specific data. Typical keys
    per action type:

    * ``CLICK`` / ``DOUBLE_CLICK``: ``{"button": "left"}``.
    * ``TYPE_TEXT``: ``{"text": "hello world"}``.
    * ``KEY_PRESS``: ``{"key": "enter"}`` or ``{"key": "ctrl+s"}``.
    * ``SCROLL``: ``{"direction": "down", "amount": 3}``.
    * ``DRAG``: ``{"from_zone_id": "a", "to_zone_id": "b"}``.
    * ``MOVE``: no extra parameters required.

    Attributes:
        type: The kind of input to perform.
        target_zone_id: Identifier of the zone to act upon.
        status: Current lifecycle status of this action.
        parameters: Action-specific payload (see above).
        timestamp: Unix timestamp when the action was created or
            last updated.
        result: Human-readable outcome description. Empty while the
            action is pending or in progress; filled on completion
            or failure.
    """

    type: ActionType
    target_zone_id: str
    status: ActionStatus = ActionStatus.PENDING
    parameters: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    result: str = ""


class TrajectoryType(Enum):
    """Strategy used to plan cursor movement toward a target zone.

    Attributes:
        DIRECT: Straight-line path (fastest, may cross other zones).
        SAFE: Path that avoids specified zones (slower but safer).
        EXPLORATORY: Wandering path used when the target location is
            uncertain and the Brush needs to search.
    """

    DIRECT = "direct"
    SAFE = "safe"
    EXPLORATORY = "exploratory"


@dataclass
class Trajectory:
    """A planned cursor path from the current position to a target zone.

    The ``points`` list defines waypoints the cursor should follow.
    For a ``SAFE`` trajectory the planner will route around the zones
    listed in ``avoid_zone_ids``.

    Attributes:
        type: Movement strategy.
        points: Ordered waypoints as ``(x, y)`` screen coordinates.
        target_zone_id: Identifier of the destination zone.
        avoid_zone_ids: Zone ids the path must not cross (relevant
            for ``SAFE`` trajectories).
    """

    type: TrajectoryType
    points: list[tuple[int, int]]
    target_zone_id: str
    avoid_zone_ids: list[str] = field(default_factory=list)
