"""Brush Controller: real-time cursor-to-zone tracking with action execution.

The BrushController is the central orchestrator for Phase 3.  It wires
together the ``ZoneTracker`` (spatial events), ``MotionPlanner``
(trajectory generation), and ``ActionExecutor`` (input injection) into a
single high-level API that the Director (Phase 4) will consume.

Typical usage::

    from ciu_agent.config.settings import get_default_settings
    from ciu_agent.core.zone_registry import ZoneRegistry
    from ciu_agent.core.zone_tracker import ZoneTracker
    from ciu_agent.core.motion_planner import MotionPlanner
    from ciu_agent.core.action_executor import ActionExecutor
    from ciu_agent.core.brush_controller import BrushController
    from ciu_agent.platform.interface import create_platform

    settings = get_default_settings()
    platform = create_platform()
    registry = ZoneRegistry()

    tracker = ZoneTracker(registry, settings)
    planner = MotionPlanner(registry, settings)
    executor = ActionExecutor(platform, registry, settings)

    brush = BrushController(
        platform=platform,
        registry=registry,
        tracker=tracker,
        planner=planner,
        executor=executor,
        settings=settings,
    )

    # Navigate and click a button
    result = brush.execute_action(action, timestamp=time.time())
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ciu_agent.config.settings import Settings
from ciu_agent.core.action_executor import ActionExecutor, ActionResult
from ciu_agent.core.motion_planner import MotionPlanner
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.core.zone_tracker import ZoneTracker
from ciu_agent.models.actions import (
    Action,
    ActionStatus,
    ActionType,
    Trajectory,
    TrajectoryType,
)
from ciu_agent.models.events import SpatialEvent, SpatialEventType
from ciu_agent.models.zone import Zone
from ciu_agent.platform.interface import PlatformInterface

logger = logging.getLogger(__name__)


@dataclass
class NavigationResult:
    """Outcome of navigating the cursor to a target zone.

    Attributes:
        success: Whether the cursor arrived in the target zone.
        target_zone_id: ID of the zone we tried to reach.
        trajectory: The trajectory that was executed.
        events: Spatial events emitted during navigation.
        error: Human-readable error description.  Empty on success.
        duration_ms: Wall-clock time for the navigation in ms.
    """

    success: bool
    target_zone_id: str
    trajectory: Trajectory
    events: list[SpatialEvent] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class BrushActionResult:
    """Combined result of navigating to a zone and executing an action.

    Attributes:
        navigation: Result of the cursor navigation phase.
        action_result: Result of the action execution phase.  ``None``
            if navigation failed before the action could run.
        events: All spatial events from both phases combined.
        success: ``True`` only when both navigation and action succeed.
        error: First error encountered, or empty string on success.
    """

    navigation: NavigationResult
    action_result: ActionResult | None
    events: list[SpatialEvent] = field(default_factory=list)
    success: bool = False
    error: str = ""


class BrushController:
    """Orchestrates cursor tracking, motion planning, and action execution.

    The BrushController is the primary interface for Phase 3.  It
    provides high-level methods that combine trajectory planning,
    cursor movement, zone verification, and input action execution
    into single calls.

    All sub-components are injected via the constructor for testability.
    The controller itself holds no OS-specific code.

    Args:
        platform: OS input/output driver for cursor movement.
        registry: Shared zone registry.
        tracker: Zone tracker for spatial event emission.
        planner: Motion planner for trajectory generation.
        executor: Action executor for input injection.
        settings: Global configuration.
    """

    def __init__(
        self,
        platform: PlatformInterface,
        registry: ZoneRegistry,
        tracker: ZoneTracker,
        planner: MotionPlanner,
        executor: ActionExecutor,
        settings: Settings,
    ) -> None:
        self._platform = platform
        self._registry = registry
        self._tracker = tracker
        self._planner = planner
        self._executor = executor
        self._settings = settings
        self._brush_lost: bool = False

    # ------------------------------------------------------------------
    # High-level API
    # ------------------------------------------------------------------

    def update(
        self,
        cursor_pos: tuple[int, int],
        timestamp: float,
    ) -> list[SpatialEvent]:
        """Process one frame of cursor tracking.

        Delegates to the ``ZoneTracker`` and returns any emitted
        spatial events.  This should be called every frame from the
        main loop.

        Args:
            cursor_pos: Current cursor ``(x, y)``.
            timestamp: Frame timestamp (Unix or monotonic).

        Returns:
            List of spatial events emitted this frame.
        """
        return self._tracker.update(cursor_pos, timestamp)

    def navigate_to_zone(
        self,
        target_zone_id: str,
        trajectory_type: TrajectoryType = TrajectoryType.DIRECT,
        avoid_zone_ids: list[str] | None = None,
    ) -> NavigationResult:
        """Move the cursor to a target zone along a planned trajectory.

        Plans a trajectory, executes it by moving the cursor through
        each waypoint, and verifies the cursor arrived in the target
        zone.  Emits spatial events for every zone transition observed
        during the motion.

        If the cursor does not end up in the target zone after the
        trajectory completes, a ``BRUSH_LOST`` event is emitted and
        the result indicates failure.

        Args:
            target_zone_id: ID of the zone to navigate to.
            trajectory_type: Planning strategy to use.
            avoid_zone_ids: Zone IDs to avoid (for SAFE trajectories).

        Returns:
            A ``NavigationResult`` describing the outcome.
        """
        start_time = time.perf_counter()
        all_events: list[SpatialEvent] = []

        # Plan the trajectory.
        try:
            trajectory = self._plan_trajectory(
                target_zone_id,
                trajectory_type,
                avoid_zone_ids or [],
            )
        except ValueError as exc:
            empty_traj = Trajectory(
                type=trajectory_type,
                points=[],
                target_zone_id=target_zone_id,
            )
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return NavigationResult(
                success=False,
                target_zone_id=target_zone_id,
                trajectory=empty_traj,
                events=[],
                error=str(exc),
                duration_ms=elapsed,
            )

        # Execute the trajectory.
        nav_timestamp = time.time()
        for point in trajectory.points:
            try:
                self._platform.move_cursor(point[0], point[1])
            except Exception as exc:
                logger.error("move_cursor failed: %s", exc)
                elapsed = (time.perf_counter() - start_time) * 1000.0
                return NavigationResult(
                    success=False,
                    target_zone_id=target_zone_id,
                    trajectory=trajectory,
                    events=all_events,
                    error=f"move_cursor failed: {exc}",
                    duration_ms=elapsed,
                )

            # Track zone transitions at each waypoint.
            events = self._tracker.update(point, nav_timestamp)
            all_events.extend(events)

        # Verify arrival.
        arrival_ok = self._verify_in_zone(target_zone_id)
        elapsed = (time.perf_counter() - start_time) * 1000.0

        if not arrival_ok:
            self._emit_brush_lost(
                target_zone_id,
                nav_timestamp,
                all_events,
            )
            return NavigationResult(
                success=False,
                target_zone_id=target_zone_id,
                trajectory=trajectory,
                events=all_events,
                error="cursor did not arrive in target zone",
                duration_ms=elapsed,
            )

        self._brush_lost = False
        return NavigationResult(
            success=True,
            target_zone_id=target_zone_id,
            trajectory=trajectory,
            events=all_events,
            error="",
            duration_ms=elapsed,
        )

    def execute_action(
        self,
        action: Action,
        timestamp: float | None = None,
        trajectory_type: TrajectoryType = TrajectoryType.DIRECT,
        avoid_zone_ids: list[str] | None = None,
    ) -> BrushActionResult:
        """Navigate to a zone and execute an action on it.

        This is the primary high-level method.  It first navigates to
        the target zone (using the specified trajectory type), then
        executes the action via the ``ActionExecutor``.

        For ``MOVE`` actions, only the navigation phase runs.

        Args:
            action: The action to execute.
            timestamp: Execution timestamp.  Defaults to ``time.time()``.
            trajectory_type: Trajectory planning strategy.
            avoid_zone_ids: Zone IDs to avoid during navigation.

        Returns:
            A ``BrushActionResult`` combining navigation and action
            outcomes.
        """
        ts = timestamp if timestamp is not None else time.time()

        # Navigate to the target zone.
        nav = self.navigate_to_zone(
            target_zone_id=action.target_zone_id,
            trajectory_type=trajectory_type,
            avoid_zone_ids=avoid_zone_ids,
        )

        if not nav.success:
            return BrushActionResult(
                navigation=nav,
                action_result=None,
                events=list(nav.events),
                success=False,
                error=nav.error,
            )

        # For MOVE actions, navigation is the action.
        if action.type == ActionType.MOVE:
            from dataclasses import replace

            completed = replace(
                action,
                status=ActionStatus.COMPLETED,
                result="ok",
                timestamp=ts,
            )
            move_result = ActionResult(
                action=completed,
                success=True,
                events=[],
                error="",
                timestamp=ts,
            )
            return BrushActionResult(
                navigation=nav,
                action_result=move_result,
                events=list(nav.events),
                success=True,
                error="",
            )

        # Execute the action.
        action_result = self._executor.execute(action, ts)
        all_events = list(nav.events) + list(action_result.events)

        return BrushActionResult(
            navigation=nav,
            action_result=action_result,
            events=all_events,
            success=action_result.success,
            error=action_result.error,
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_current_zone(self) -> str | None:
        """Return the ID of the zone the cursor currently occupies.

        Returns:
            Zone ID string or ``None``.
        """
        return self._tracker.get_current_zone()

    def get_current_zone_object(self) -> Zone | None:
        """Return the Zone object the cursor currently occupies.

        Returns:
            The ``Zone`` instance or ``None``.
        """
        return self._tracker.get_current_zone_object()

    def get_event_history(self, limit: int = 50) -> list[SpatialEvent]:
        """Return recent spatial events from the tracker.

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of recent events, oldest first.
        """
        return self._tracker.get_event_history(limit)

    def get_cursor_pos(self) -> tuple[int, int]:
        """Return the current cursor position from the platform.

        Returns:
            Cursor ``(x, y)`` in logical coordinates.
        """
        return self._platform.get_cursor_pos()

    def get_zones_at_cursor(self) -> list[Zone]:
        """Return all zones containing the current cursor position.

        Returns:
            Zones sorted by ascending area (smallest first).
        """
        x, y = self._platform.get_cursor_pos()
        return self._registry.find_at_point(x, y)

    @property
    def is_brush_lost(self) -> bool:
        """Whether the brush is currently in a lost state.

        The brush is considered lost when the last navigation attempt
        failed to place the cursor in the target zone.  Cleared on
        the next successful navigation.
        """
        return self._brush_lost

    @property
    def zone_count(self) -> int:
        """Number of zones in the registry."""
        return self._registry.count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _plan_trajectory(
        self,
        target_zone_id: str,
        trajectory_type: TrajectoryType,
        avoid_zone_ids: list[str],
    ) -> Trajectory:
        """Plan a trajectory to the target zone.

        Args:
            target_zone_id: Destination zone ID.
            trajectory_type: Strategy to use.
            avoid_zone_ids: Zones to avoid (SAFE only).

        Returns:
            A ``Trajectory`` with waypoints.

        Raises:
            ValueError: If the target zone is not in the registry.
        """
        start = self._platform.get_cursor_pos()

        if trajectory_type == TrajectoryType.DIRECT:
            return self._planner.plan_direct(start, target_zone_id)

        if trajectory_type == TrajectoryType.SAFE:
            return self._planner.plan_safe(
                start,
                target_zone_id,
                avoid_zone_ids,
            )

        # EXPLORATORY — target zone gives the scan region.
        zone = self._registry.get(target_zone_id)
        if zone is None:
            raise ValueError(
                f"Target zone '{target_zone_id}' not found in registry"
            )
        b = zone.bounds
        return self._planner.plan_exploratory(
            start,
            (b.x, b.y, b.width, b.height),
        )

    def _verify_in_zone(self, zone_id: str) -> bool:
        """Check if the cursor is currently inside a specific zone.

        Args:
            zone_id: Zone ID to verify against.

        Returns:
            ``True`` if the cursor is within the zone bounds.
        """
        zone = self._registry.get(zone_id)
        if zone is None:
            return False
        x, y = self._platform.get_cursor_pos()
        return zone.contains_point(x, y)

    def _emit_brush_lost(
        self,
        expected_zone_id: str,
        timestamp: float,
        events: list[SpatialEvent],
    ) -> None:
        """Emit a BRUSH_LOST event and set the brush-lost flag.

        Args:
            expected_zone_id: The zone we expected to be in.
            timestamp: Event timestamp.
            events: Mutable list to append the event to.
        """
        self._brush_lost = True
        pos = self._platform.get_cursor_pos()
        event = SpatialEvent(
            type=SpatialEventType.BRUSH_LOST,
            zone_id="",
            timestamp=timestamp,
            position=pos,
            data={"expected_zone": expected_zone_id},
        )
        events.append(event)
        logger.warning(
            "brush lost: expected zone %r, cursor at %s",
            expected_zone_id,
            pos,
        )

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """Human-readable summary."""
        zone = self._tracker.get_current_zone() or "none"
        return (
            f"BrushController(current_zone={zone!r}, "
            f"brush_lost={self._brush_lost}, "
            f"zones={self._registry.count})"
        )
