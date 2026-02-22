"""Step executor: runs individual task steps through the BrushController.

The ``StepExecutor`` bridges the gap between the Director's high-level
``TaskStep`` objects and the low-level ``BrushController`` API.  For
each step it resolves the target zone, maps the action-type string to
an ``ActionType`` enum, builds an ``Action``, and delegates to
``BrushController.execute_action``.

This module is part of Phase 4 (Director).

Typical usage::

    from ciu_agent.config.settings import get_default_settings
    from ciu_agent.core.brush_controller import BrushController
    from ciu_agent.core.zone_registry import ZoneRegistry
    from ciu_agent.core.step_executor import StepExecutor
    from ciu_agent.models.task import TaskStep

    settings = get_default_settings()
    # ... build brush, registry as usual ...
    executor = StepExecutor(brush, registry, settings)

    step = TaskStep(
        step_number=1,
        zone_id="btn_save",
        zone_label="Save",
        action_type="click",
    )
    result = executor.execute(step, timestamp=time.time())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ciu_agent.config.settings import Settings
from ciu_agent.core.brush_controller import BrushActionResult, BrushController
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.actions import Action, ActionType
from ciu_agent.models.events import SpatialEvent
from ciu_agent.models.task import TaskStep

logger = logging.getLogger(__name__)

# Mapping from action-type strings (as produced by the planner) to
# ``ActionType`` enum values understood by the BrushController.
_ACTION_TYPE_MAP: dict[str, ActionType] = {
    "click": ActionType.CLICK,
    "double_click": ActionType.DOUBLE_CLICK,
    "type_text": ActionType.TYPE_TEXT,
    "key_press": ActionType.KEY_PRESS,
    "scroll": ActionType.SCROLL,
    "move": ActionType.MOVE,
}


@dataclass
class StepResult:
    """Result of executing a single ``TaskStep``.

    Attributes:
        step: The step that was executed.
        success: Whether the step completed successfully.
        action_result: The ``BrushActionResult`` returned by the
            controller.  ``None`` if the step could not even start
            (e.g. unknown action type or missing zone).
        events: Spatial events emitted during execution.
        error: Human-readable error description.  Empty on success.
        error_type: Machine-readable error category.  One of:

            * ``""`` -- no error (success).
            * ``"zone_not_found"`` -- target zone is not in the
              registry.
            * ``"action_failed"`` -- the action itself failed (or the
              action type string was unrecognised).
            * ``"brush_lost"`` -- navigation succeeded but the cursor
              did not arrive in the target zone.
            * ``"timeout"`` -- reserved for future use.

        timestamp: Unix timestamp when the result was produced.
    """

    step: TaskStep
    success: bool
    action_result: BrushActionResult | None
    events: list[SpatialEvent] = field(default_factory=list)
    error: str = ""
    error_type: str = ""
    timestamp: float = 0.0


class StepExecutor:
    """Executes individual ``TaskStep`` objects through the BrushController.

    The executor is stateless between calls -- each ``execute`` invocation
    is independent.  All OS interaction is delegated to the injected
    ``BrushController``.

    Args:
        brush: The ``BrushController`` used for navigation and action
            execution.
        registry: The ``ZoneRegistry`` used to verify that target zones
            exist before attempting navigation.
        settings: Global configuration (reserved for future tuning
            knobs such as per-step timeouts).
    """

    def __init__(
        self,
        brush: BrushController,
        registry: ZoneRegistry,
        settings: Settings,
    ) -> None:
        self._brush = brush
        self._registry = registry
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, step: TaskStep, timestamp: float) -> StepResult:
        """Execute a single task step.

        The method follows this sequence:

        1. Map the step's ``action_type`` string to an ``ActionType``
           enum.  If the string is unrecognised the step fails
           immediately with ``error_type="action_failed"``.
        2. Verify that ``step.zone_id`` exists in the zone registry.
           If not, the step fails with ``error_type="zone_not_found"``.
        3. Build an ``Action`` and delegate to
           ``BrushController.execute_action``.
        4. Translate the ``BrushActionResult`` into a ``StepResult``,
           distinguishing navigation failures (``brush_lost``) from
           action failures (``action_failed``).

        Args:
            step: The task step to execute.
            timestamp: Execution timestamp (Unix seconds).

        Returns:
            A ``StepResult`` describing the outcome.
        """
        # 1. Map action type string -> ActionType enum.
        action_type = self._map_action_type(step.action_type)
        if action_type is None:
            logger.warning(
                "step %d: unknown action_type %r",
                step.step_number,
                step.action_type,
            )
            return StepResult(
                step=step,
                success=False,
                action_result=None,
                events=[],
                error=f"Unknown action type: {step.action_type!r}",
                error_type="action_failed",
                timestamp=timestamp,
            )

        # 2. Verify target zone exists.
        if not self._registry.contains(step.zone_id):
            logger.warning(
                "step %d: zone %r not found in registry",
                step.step_number,
                step.zone_id,
            )
            return StepResult(
                step=step,
                success=False,
                action_result=None,
                events=[],
                error=f"Zone not found: {step.zone_id!r}",
                error_type="zone_not_found",
                timestamp=timestamp,
            )

        # 3. Build the Action and execute.
        action = Action(
            type=action_type,
            target_zone_id=step.zone_id,
            parameters=dict(step.parameters),
        )
        brush_result = self._brush.execute_action(action, timestamp)

        # 4. Translate BrushActionResult -> StepResult.
        return self._translate_result(step, brush_result, timestamp)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _map_action_type(self, action_type_str: str) -> ActionType | None:
        """Map a planner action-type string to an ``ActionType`` enum.

        Args:
            action_type_str: One of ``"click"``, ``"double_click"``,
                ``"type_text"``, ``"key_press"``, ``"scroll"``,
                ``"move"``.

        Returns:
            The corresponding ``ActionType``, or ``None`` if the
            string is not recognised.
        """
        return _ACTION_TYPE_MAP.get(action_type_str)

    def _translate_result(
        self,
        step: TaskStep,
        brush_result: BrushActionResult,
        timestamp: float,
    ) -> StepResult:
        """Convert a ``BrushActionResult`` into a ``StepResult``.

        Distinguishes between navigation failures (brush lost) and
        action-phase failures so that the Director can apply different
        recovery strategies.

        Args:
            step: The originating task step.
            brush_result: Result from the brush controller.
            timestamp: Execution timestamp.

        Returns:
            A fully populated ``StepResult``.
        """
        if brush_result.success:
            return StepResult(
                step=step,
                success=True,
                action_result=brush_result,
                events=list(brush_result.events),
                error="",
                error_type="",
                timestamp=timestamp,
            )

        # Determine error category.
        if not brush_result.navigation.success:
            error_type = "brush_lost"
        else:
            error_type = "action_failed"

        return StepResult(
            step=step,
            success=False,
            action_result=brush_result,
            events=list(brush_result.events),
            error=brush_result.error,
            error_type=error_type,
            timestamp=timestamp,
        )

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """Human-readable summary."""
        return f"StepExecutor(zones={self._registry.count})"
