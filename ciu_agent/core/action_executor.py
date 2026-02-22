"""Execute input actions with zone verification.

The ``ActionExecutor`` performs actual input actions (click, type, scroll,
etc.) via the platform layer after verifying the cursor is positioned
inside the target zone.  Each execution produces an ``ActionResult``
containing the updated action, success flag, any emitted spatial events,
and timing information.

This module is part of Phase 3 (Brush Controller).

Typical usage::

    from ciu_agent.platform.interface import create_platform
    from ciu_agent.config.settings import get_default_settings
    from ciu_agent.core.zone_registry import ZoneRegistry

    platform = create_platform()
    settings = get_default_settings()
    registry = ZoneRegistry()

    executor = ActionExecutor(platform, registry, settings)
    result = executor.execute(action, timestamp=time.time())
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from ciu_agent.config.settings import Settings
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.actions import Action, ActionStatus, ActionType
from ciu_agent.models.events import SpatialEvent, SpatialEventType
from ciu_agent.models.zone import Zone
from ciu_agent.platform.interface import PlatformInterface

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Outcome of executing an ``Action`` via the ``ActionExecutor``.

    Attributes:
        action: The action after execution, with its ``status`` updated
            to ``COMPLETED`` or ``FAILED``.
        success: Whether the action completed without error.
        events: Spatial events emitted during execution (e.g.
            ``ZONE_CLICK``, ``ZONE_TYPE``).
        error: Human-readable error description.  Empty string on
            success.
        timestamp: Unix timestamp when the result was produced.
    """

    action: Action
    success: bool
    events: list[SpatialEvent]
    error: str
    timestamp: float


class ActionExecutor:
    """Executes input actions against screen zones via the platform layer.

    Before performing any action the executor verifies that the cursor
    is currently positioned inside the target zone.  If not, the action
    fails immediately with a descriptive error.

    All platform exceptions are caught and converted to ``FAILED``
    results so that callers never see raw OS-level errors.

    Args:
        platform: OS-specific input/output driver.
        registry: Zone registry for target zone lookups.
        settings: Global configuration.
    """

    def __init__(
        self,
        platform: PlatformInterface,
        registry: ZoneRegistry,
        settings: Settings,
    ) -> None:
        self._platform = platform
        self._registry = registry
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, action: Action, timestamp: float) -> ActionResult:
        """Execute an input action directed at a target zone.

        Steps:

        1. Look up the target zone in the registry.
        2. Verify the cursor is inside the target zone.
        3. Dispatch to the appropriate handler for the action type.
        4. Return an ``ActionResult`` with the updated action and any
           emitted spatial events.

        Args:
            action: The action to execute.  Must have ``status ==
                PENDING``.
            timestamp: Unix timestamp to associate with the execution.

        Returns:
            An ``ActionResult`` describing the outcome.
        """
        # 1. Look up target zone.
        zone = self._registry.get(action.target_zone_id)
        if zone is None:
            failed = replace(
                action,
                status=ActionStatus.FAILED,
                result=f"zone '{action.target_zone_id}' not found in registry",
                timestamp=timestamp,
            )
            return ActionResult(
                action=failed,
                success=False,
                events=[],
                error=f"zone '{action.target_zone_id}' not found in registry",
                timestamp=timestamp,
            )

        # 2. Verify cursor is inside the target zone.
        if not self._verify_cursor_in_zone(zone):
            failed = replace(
                action,
                status=ActionStatus.FAILED,
                result="cursor not in target zone",
                timestamp=timestamp,
            )
            return ActionResult(
                action=failed,
                success=False,
                events=[],
                error="cursor not in target zone",
                timestamp=timestamp,
            )

        # 3. Mark action as in-progress.
        action = replace(
            action,
            status=ActionStatus.IN_PROGRESS,
            timestamp=timestamp,
        )

        # 4. Dispatch to handler.
        handler = self._DISPATCH.get(action.type)
        if handler is None:
            failed = replace(
                action,
                status=ActionStatus.FAILED,
                result=f"unsupported action type: {action.type.value}",
                timestamp=timestamp,
            )
            return ActionResult(
                action=failed,
                success=False,
                events=[],
                error=f"unsupported action type: {action.type.value}",
                timestamp=timestamp,
            )

        return handler(self, action, zone, timestamp)

    # ------------------------------------------------------------------
    # Private handlers
    # ------------------------------------------------------------------

    def _execute_click(
        self,
        action: Action,
        zone: Zone,
        timestamp: float,
    ) -> ActionResult:
        """Handle a single-click action.

        Uses the click point from ``action.parameters`` if provided,
        otherwise falls back to the zone center.  The mouse button
        defaults to ``"left"`` unless overridden in parameters.
        """
        x, y = self._click_point(action, zone)
        button: str = action.parameters.get("button", "left")

        try:
            self._platform.click(x, y, button)
        except Exception as exc:
            return self._fail(action, str(exc), timestamp)

        event = SpatialEvent(
            type=SpatialEventType.ZONE_CLICK,
            zone_id=zone.id,
            timestamp=timestamp,
            position=(x, y),
            data={"button": button},
        )
        return self._succeed(action, [event], timestamp)

    def _execute_double_click(
        self,
        action: Action,
        zone: Zone,
        timestamp: float,
    ) -> ActionResult:
        """Handle a double-click action.

        Emits a ``ZONE_CLICK`` event with ``double=True`` in its data
        payload.
        """
        x, y = self._click_point(action, zone)
        button: str = action.parameters.get("button", "left")

        try:
            self._platform.double_click(x, y, button)
        except Exception as exc:
            return self._fail(action, str(exc), timestamp)

        event = SpatialEvent(
            type=SpatialEventType.ZONE_CLICK,
            zone_id=zone.id,
            timestamp=timestamp,
            position=(x, y),
            data={"button": button, "double": True},
        )
        return self._succeed(action, [event], timestamp)

    def _execute_type_text(
        self,
        action: Action,
        zone: Zone,
        timestamp: float,
    ) -> ActionResult:
        """Handle a text-typing action.

        Requires ``action.parameters["text"]`` to be present.
        """
        text = action.parameters.get("text")
        if text is None:
            return self._fail(
                action,
                "missing required parameter 'text'",
                timestamp,
            )

        try:
            self._platform.type_text(text)
        except Exception as exc:
            return self._fail(action, str(exc), timestamp)

        cx, cy = zone.bounds.center()
        event = SpatialEvent(
            type=SpatialEventType.ZONE_TYPE,
            zone_id=zone.id,
            timestamp=timestamp,
            position=(cx, cy),
            data={"text": text},
        )
        return self._succeed(action, [event], timestamp)

    def _execute_key_press(
        self,
        action: Action,
        zone: Zone,
        timestamp: float,
    ) -> ActionResult:
        """Handle a single key or key-combo press.

        Requires ``action.parameters["key"]`` to be present.  Does not
        emit a dedicated spatial event beyond the action result itself.
        """
        key = action.parameters.get("key")
        if key is None:
            return self._fail(
                action,
                "missing required parameter 'key'",
                timestamp,
            )

        try:
            self._platform.key_press(key)
        except Exception as exc:
            return self._fail(action, str(exc), timestamp)

        return self._succeed(action, [], timestamp)

    def _execute_scroll(
        self,
        action: Action,
        zone: Zone,
        timestamp: float,
    ) -> ActionResult:
        """Handle a scroll action inside a zone.

        Defaults to 3 scroll increments downward if ``amount`` and
        ``direction`` are not specified in the action parameters.
        Positive ``amount`` values passed to the platform mean "scroll
        up"; negative means "scroll down".
        """
        amount: int = int(action.parameters.get("amount", 3))
        direction: str = action.parameters.get("direction", "down")
        signed_amount = -amount if direction == "down" else amount

        cx, cy = zone.bounds.center()
        try:
            self._platform.scroll(cx, cy, signed_amount)
        except Exception as exc:
            return self._fail(action, str(exc), timestamp)

        return self._succeed(action, [], timestamp)

    def _execute_drag(
        self,
        action: Action,
        zone: Zone,
        timestamp: float,
    ) -> ActionResult:
        """Placeholder handler for drag actions.

        Drag is not yet fully implemented.  Returns success with a log
        warning so that callers are aware of the limitation.
        """
        logger.warning("drag action is not yet fully implemented")
        return self._succeed(action, [], timestamp)

    def _execute_move(
        self,
        action: Action,
        zone: Zone,
        timestamp: float,
    ) -> ActionResult:
        """Handle a cursor-move action to the zone center."""
        cx, cy = zone.bounds.center()
        try:
            self._platform.move_cursor(cx, cy)
        except Exception as exc:
            return self._fail(action, str(exc), timestamp)

        return self._succeed(action, [], timestamp)

    # ------------------------------------------------------------------
    # Dispatch table
    # ------------------------------------------------------------------

    _DISPATCH: dict[
        ActionType,
        Callable[[ActionExecutor, Action, Zone, float], ActionResult],
    ] = {
        ActionType.CLICK: _execute_click,
        ActionType.DOUBLE_CLICK: _execute_double_click,
        ActionType.TYPE_TEXT: _execute_type_text,
        ActionType.KEY_PRESS: _execute_key_press,
        ActionType.SCROLL: _execute_scroll,
        ActionType.DRAG: _execute_drag,
        ActionType.MOVE: _execute_move,
    }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _verify_cursor_in_zone(self, zone: Zone) -> bool:
        """Check whether the cursor is currently inside the zone bounds.

        Args:
            zone: The zone to check against.

        Returns:
            ``True`` if the current cursor position is within the zone.
        """
        cx, cy = self._platform.get_cursor_pos()
        return zone.contains_point(cx, cy)

    @staticmethod
    def _click_point(action: Action, zone: Zone) -> tuple[int, int]:
        """Determine the click coordinates for an action.

        Uses explicit ``x`` / ``y`` from ``action.parameters`` when
        present, otherwise falls back to the zone center.

        Args:
            action: The action whose parameters may specify a point.
            zone: The target zone (used for its center fallback).

        Returns:
            An ``(x, y)`` tuple of screen coordinates.
        """
        if "x" in action.parameters and "y" in action.parameters:
            return (int(action.parameters["x"]), int(action.parameters["y"]))
        return zone.bounds.center()

    def _succeed(
        self,
        action: Action,
        events: list[SpatialEvent],
        timestamp: float,
    ) -> ActionResult:
        """Build a successful ``ActionResult``.

        Args:
            action: The in-progress action to mark as completed.
            events: Spatial events emitted during execution.
            timestamp: Unix timestamp for the result.

        Returns:
            An ``ActionResult`` with ``success=True``.
        """
        completed = replace(
            action,
            status=ActionStatus.COMPLETED,
            result="ok",
            timestamp=timestamp,
        )
        return ActionResult(
            action=completed,
            success=True,
            events=events,
            error="",
            timestamp=timestamp,
        )

    def _fail(
        self,
        action: Action,
        error: str,
        timestamp: float,
    ) -> ActionResult:
        """Build a failed ``ActionResult``.

        Args:
            action: The action to mark as failed.
            error: Human-readable error description.
            timestamp: Unix timestamp for the result.

        Returns:
            An ``ActionResult`` with ``success=False``.
        """
        failed = replace(
            action,
            status=ActionStatus.FAILED,
            result=error,
            timestamp=timestamp,
        )
        logger.error("action %s failed: %s", action.type.value, error)
        return ActionResult(
            action=failed,
            success=False,
            events=[],
            error=error,
            timestamp=timestamp,
        )
