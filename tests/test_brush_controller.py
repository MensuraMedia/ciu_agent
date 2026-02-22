"""Comprehensive unit tests for ciu_agent.core.brush_controller.

Tests cover update/tracking, navigate_to_zone, execute_action, query
methods, and edge cases.  Uses a MockPlatform with cursor-position
tracking and real ZoneRegistry / ZoneTracker / MotionPlanner /
ActionExecutor instances (integration-style).
"""

from __future__ import annotations

import time

import numpy as np
from numpy.typing import NDArray

from ciu_agent.config.settings import Settings
from ciu_agent.core.action_executor import ActionExecutor
from ciu_agent.core.brush_controller import (
    BrushActionResult,
    BrushController,
    NavigationResult,
)
from ciu_agent.core.motion_planner import MotionPlanner
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.core.zone_tracker import ZoneTracker
from ciu_agent.models.actions import (
    Action,
    ActionStatus,
    ActionType,
    TrajectoryType,
)
from ciu_agent.models.events import SpatialEvent, SpatialEventType
from ciu_agent.models.zone import Rectangle, Zone, ZoneState, ZoneType
from ciu_agent.platform.interface import PlatformInterface, WindowInfo

# ------------------------------------------------------------------
# MockPlatform
# ------------------------------------------------------------------


class MockPlatform(PlatformInterface):
    """Test double for PlatformInterface with cursor-position tracking.

    ``move_cursor(x, y)`` updates the internal ``_cursor_pos`` so that
    subsequent calls to ``get_cursor_pos()`` return ``(x, y)``.  All
    calls are recorded in ``calls`` for assertion purposes.

    Set ``raise_on`` to a method name to make that method raise a
    ``RuntimeError`` when invoked.
    """

    def __init__(
        self,
        cursor_pos: tuple[int, int] = (0, 0),
        screen_size: tuple[int, int] = (1920, 1080),
    ) -> None:
        self._cursor_pos: tuple[int, int] = cursor_pos
        self._screen_size: tuple[int, int] = screen_size
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.raise_on: str | None = None

    def _maybe_raise(self, method: str) -> None:
        if self.raise_on == method:
            raise RuntimeError(f"MockPlatform: {method} forced error")

    # -- Screen capture ------------------------------------------------

    def capture_frame(self) -> NDArray[np.uint8]:
        self.calls.append(("capture_frame", ()))
        return np.zeros(
            (self._screen_size[1], self._screen_size[0], 3),
            dtype=np.uint8,
        )

    # -- Cursor --------------------------------------------------------

    def get_cursor_pos(self) -> tuple[int, int]:
        self.calls.append(("get_cursor_pos", ()))
        return self._cursor_pos

    def move_cursor(self, x: int, y: int) -> None:
        self._maybe_raise("move_cursor")
        self._cursor_pos = (x, y)
        self.calls.append(("move_cursor", (x, y)))

    # -- Mouse ---------------------------------------------------------

    def click(self, x: int, y: int, button: str = "left") -> None:
        self._maybe_raise("click")
        self.calls.append(("click", (x, y, button)))

    def double_click(
        self, x: int, y: int, button: str = "left"
    ) -> None:
        self._maybe_raise("double_click")
        self.calls.append(("double_click", (x, y, button)))

    def scroll(self, x: int, y: int, amount: int) -> None:
        self._maybe_raise("scroll")
        self.calls.append(("scroll", (x, y, amount)))

    # -- Keyboard ------------------------------------------------------

    def type_text(self, text: str) -> None:
        self._maybe_raise("type_text")
        self.calls.append(("type_text", (text,)))

    def key_press(self, key: str) -> None:
        self._maybe_raise("key_press")
        self.calls.append(("key_press", (key,)))

    # -- Screen / window queries ---------------------------------------

    def get_screen_size(self) -> tuple[int, int]:
        self.calls.append(("get_screen_size", ()))
        return self._screen_size

    def get_active_window(self) -> WindowInfo:
        self.calls.append(("get_active_window", ()))
        return WindowInfo(
            title="mock", x=0, y=0, width=800, height=600
        )

    def list_windows(self) -> list[WindowInfo]:
        self.calls.append(("list_windows", ()))
        return [self.get_active_window()]

    def get_platform_name(self) -> str:
        return "mock"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_zone(
    zone_id: str = "z1",
    x: int = 100,
    y: int = 100,
    width: int = 200,
    height: int = 100,
    zone_type: ZoneType = ZoneType.BUTTON,
    label: str = "TestZone",
    state: ZoneState = ZoneState.ENABLED,
) -> Zone:
    """Build a ``Zone`` with sensible defaults."""
    return Zone(
        id=zone_id,
        bounds=Rectangle(x=x, y=y, width=width, height=height),
        type=zone_type,
        label=label,
        state=state,
    )


def _make_action(
    action_type: ActionType = ActionType.CLICK,
    target_zone_id: str = "z1",
    parameters: dict | None = None,
) -> Action:
    """Build an ``Action`` with sensible defaults."""
    return Action(
        type=action_type,
        target_zone_id=target_zone_id,
        parameters=parameters or {},
    )


def _build_controller(
    cursor_pos: tuple[int, int] = (0, 0),
    zones: list[Zone] | None = None,
    settings: Settings | None = None,
) -> tuple[
    BrushController,
    MockPlatform,
    ZoneRegistry,
    ZoneTracker,
    MotionPlanner,
    ActionExecutor,
]:
    """Construct a full BrushController stack with a MockPlatform.

    Returns the controller and all sub-components for direct access.
    """
    platform = MockPlatform(cursor_pos=cursor_pos)
    registry = ZoneRegistry()
    if zones:
        registry.register_many(zones)

    s = settings or Settings()
    tracker = ZoneTracker(registry, s)
    planner = MotionPlanner(registry, s)
    executor = ActionExecutor(platform, registry, s)

    brush = BrushController(
        platform=platform,
        registry=registry,
        tracker=tracker,
        planner=planner,
        executor=executor,
        settings=s,
    )
    return brush, platform, registry, tracker, planner, executor


# ------------------------------------------------------------------
# 1. update() / Tracking
# ------------------------------------------------------------------


class TestBrushController_Update:
    """Tests for the ``update()`` method (zone-tracking delegation)."""

    def test_update_delegates_to_zone_tracker(self) -> None:
        """update() should pass through to ZoneTracker.update()."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, *_ = _build_controller(
            cursor_pos=(150, 150), zones=[zone]
        )
        events = brush.update((150, 150), 1.0)
        # Cursor is inside z1 on the first frame -> ZONE_ENTER
        assert len(events) >= 1
        assert events[0].type == SpatialEventType.ZONE_ENTER
        assert events[0].zone_id == "z1"

    def test_update_returns_spatial_events(self) -> None:
        """update() should return the event list from the tracker."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, *_ = _build_controller(zones=[zone])
        events = brush.update((150, 150), 1.0)
        assert isinstance(events, list)
        for ev in events:
            assert isinstance(ev, SpatialEvent)

    def test_multiple_updates_emit_correct_events(self) -> None:
        """Successive updates should emit enter/exit/enter events."""
        z1 = _make_zone("z1", 100, 100, 200, 100)
        z2 = _make_zone("z2", 500, 500, 200, 100)
        brush, *_ = _build_controller(zones=[z1, z2])

        # Enter z1
        ev1 = brush.update((150, 150), 1.0)
        assert any(
            e.type == SpatialEventType.ZONE_ENTER and e.zone_id == "z1"
            for e in ev1
        )

        # Exit z1, enter z2
        ev2 = brush.update((550, 550), 2.0)
        assert any(
            e.type == SpatialEventType.ZONE_EXIT and e.zone_id == "z1"
            for e in ev2
        )
        assert any(
            e.type == SpatialEventType.ZONE_ENTER
            and e.zone_id == "z2"
            for e in ev2
        )

    def test_cursor_entering_zone_emits_zone_enter(self) -> None:
        """Moving cursor from outside to inside a zone emits ZONE_ENTER."""
        zone = _make_zone("btn", 200, 200, 100, 50)
        brush, *_ = _build_controller(zones=[zone])

        # Start outside
        events_outside = brush.update((0, 0), 1.0)
        assert not any(
            e.type == SpatialEventType.ZONE_ENTER
            for e in events_outside
        )

        # Move inside
        events_enter = brush.update((250, 225), 2.0)
        assert any(
            e.type == SpatialEventType.ZONE_ENTER
            and e.zone_id == "btn"
            for e in events_enter
        )

    def test_cursor_leaving_zone_emits_zone_exit(self) -> None:
        """Moving cursor from inside a zone to outside emits ZONE_EXIT."""
        zone = _make_zone("btn", 200, 200, 100, 50)
        brush, *_ = _build_controller(zones=[zone])

        # Enter zone
        brush.update((250, 225), 1.0)

        # Leave zone
        events_exit = brush.update((0, 0), 2.0)
        assert any(
            e.type == SpatialEventType.ZONE_EXIT
            and e.zone_id == "btn"
            for e in events_exit
        )

    def test_update_outside_all_zones_returns_no_events(self) -> None:
        """update() with cursor outside all zones emits nothing."""
        zone = _make_zone("z1", 500, 500, 50, 50)
        brush, *_ = _build_controller(zones=[zone])
        events = brush.update((0, 0), 1.0)
        assert events == []


# ------------------------------------------------------------------
# 2. navigate_to_zone()
# ------------------------------------------------------------------


class TestBrushController_NavigateToZone:
    """Tests for ``navigate_to_zone()``."""

    def test_successful_direct_navigation(self) -> None:
        """Navigating to a registered zone succeeds."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        result = brush.navigate_to_zone("z1")

        assert isinstance(result, NavigationResult)
        assert result.success is True
        assert result.target_zone_id == "z1"
        assert result.error == ""

    def test_cursor_ends_in_target_zone(self) -> None:
        """After successful navigation the cursor is inside the zone."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        brush.navigate_to_zone("z1")

        cx, cy = platform._cursor_pos
        assert zone.contains_point(cx, cy)

    def test_navigation_emits_events_for_zones_crossed(self) -> None:
        """Navigating through zones emits zone-transition events."""
        z_start = _make_zone("z_start", 0, 0, 50, 50)
        z_target = _make_zone("z_target", 100, 100, 200, 100)
        brush, *_ = _build_controller(
            cursor_pos=(25, 25), zones=[z_start, z_target]
        )

        # First seed the tracker with the starting position
        brush.update((25, 25), 0.5)

        result = brush.navigate_to_zone("z_target")
        assert result.success is True
        # Should have at least one event from traversing zones
        assert len(result.events) >= 1

    def test_nonexistent_zone_fails(self) -> None:
        """Navigating to an unregistered zone returns failure."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, *_ = _build_controller(zones=[zone])

        result = brush.navigate_to_zone("does_not_exist")

        assert result.success is False
        assert "not found" in result.error.lower()
        assert result.target_zone_id == "does_not_exist"

    def test_brush_lost_event_on_failed_arrival(self) -> None:
        """A BRUSH_LOST event is emitted when the cursor misses."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        # After navigation the mock will have the cursor at the
        # zone center (trajectory endpoint).  To simulate a miss we
        # make move_cursor NOT update the position by overriding.
        def broken_move(x: int, y: int) -> None:
            # Record the call but do NOT update _cursor_pos.
            platform.calls.append(("move_cursor", (x, y)))

        platform.move_cursor = broken_move  # type: ignore[assignment]

        result = brush.navigate_to_zone("z1")

        assert result.success is False
        brush_lost_events = [
            e
            for e in result.events
            if e.type == SpatialEventType.BRUSH_LOST
        ]
        assert len(brush_lost_events) >= 1

    def test_is_brush_lost_set_on_failed_navigation(self) -> None:
        """is_brush_lost is True after a failed navigation."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        # Break move_cursor so cursor stays at (0, 0).
        platform.move_cursor = lambda x, y: platform.calls.append(  # type: ignore[assignment]
            ("move_cursor", (x, y))
        )

        brush.navigate_to_zone("z1")

        assert brush.is_brush_lost is True

    def test_is_brush_lost_cleared_on_success(self) -> None:
        """is_brush_lost is cleared after a successful navigation."""
        z1 = _make_zone("z1", 100, 100, 200, 100)
        z2 = _make_zone("z2", 500, 500, 200, 100)
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[z1, z2]
        )

        # First: force a failed navigation to set brush_lost.
        platform.move_cursor = lambda x, y: platform.calls.append(  # type: ignore[assignment]
            ("move_cursor", (x, y))
        )
        brush.navigate_to_zone("z1")
        assert brush.is_brush_lost is True

        # Restore normal move_cursor.
        def real_move(x: int, y: int) -> None:
            platform._cursor_pos = (x, y)
            platform.calls.append(("move_cursor", (x, y)))

        platform.move_cursor = real_move  # type: ignore[assignment]

        brush.navigate_to_zone("z2")
        assert brush.is_brush_lost is False

    def test_safe_trajectory_avoids_zones(self) -> None:
        """SAFE trajectory should route around avoid-zones."""
        target = _make_zone("target", 400, 0, 100, 100)
        avoid = _make_zone("avoid", 200, 0, 100, 100)
        brush, *_ = _build_controller(
            cursor_pos=(0, 50), zones=[target, avoid]
        )

        result = brush.navigate_to_zone(
            "target",
            trajectory_type=TrajectoryType.SAFE,
            avoid_zone_ids=["avoid"],
        )

        assert result.success is True
        assert result.trajectory.type == TrajectoryType.SAFE

    def test_navigation_result_has_nonneg_duration(self) -> None:
        """NavigationResult.duration_ms is >= 0."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        result = brush.navigate_to_zone("z1")
        assert result.duration_ms >= 0.0

    def test_navigation_result_trajectory_has_correct_type(self) -> None:
        """The trajectory in the result matches the requested type."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        result = brush.navigate_to_zone(
            "z1", trajectory_type=TrajectoryType.DIRECT
        )
        assert result.trajectory.type == TrajectoryType.DIRECT


# ------------------------------------------------------------------
# 3. execute_action()
# ------------------------------------------------------------------


class TestBrushController_ExecuteAction:
    """Tests for ``execute_action()``."""

    def test_successful_click(self) -> None:
        """Navigate + click returns success."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        action = _make_action(ActionType.CLICK, "btn")
        result = brush.execute_action(action, timestamp=1000.0)

        assert isinstance(result, BrushActionResult)
        assert result.success is True
        assert result.navigation.success is True
        assert result.action_result is not None
        assert result.action_result.success is True
        assert result.error == ""

    def test_failed_navigation_skips_action(self) -> None:
        """When navigation fails, action_result is None."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        # Break move_cursor.
        platform.move_cursor = lambda x, y: platform.calls.append(  # type: ignore[assignment]
            ("move_cursor", (x, y))
        )

        action = _make_action(ActionType.CLICK, "btn")
        result = brush.execute_action(action, timestamp=1000.0)

        assert result.success is False
        assert result.action_result is None
        # No click should have been issued.
        click_calls = [
            c for c in platform.calls if c[0] == "click"
        ]
        assert len(click_calls) == 0

    def test_move_action_only_navigates(self) -> None:
        """MOVE action navigates but performs no separate action."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        action = _make_action(ActionType.MOVE, "btn")
        result = brush.execute_action(action, timestamp=1000.0)

        assert result.success is True
        assert result.navigation.success is True
        assert result.action_result is not None
        assert result.action_result.success is True
        assert result.action_result.action.status == ActionStatus.COMPLETED
        # No click / type_text / key_press should appear.
        non_move_calls = [
            c
            for c in platform.calls
            if c[0] in ("click", "type_text", "key_press")
        ]
        assert len(non_move_calls) == 0

    def test_type_text_action(self) -> None:
        """TYPE_TEXT action navigates then types text."""
        zone = _make_zone(
            "field", 100, 100, 200, 100,
            zone_type=ZoneType.TEXT_FIELD,
        )
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        action = _make_action(
            ActionType.TYPE_TEXT,
            "field",
            parameters={"text": "hello"},
        )
        result = brush.execute_action(action, timestamp=1000.0)

        assert result.success is True
        type_calls = [
            c for c in platform.calls if c[0] == "type_text"
        ]
        assert len(type_calls) == 1
        assert type_calls[0][1] == ("hello",)

    def test_key_press_action(self) -> None:
        """KEY_PRESS action navigates then presses a key."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        action = _make_action(
            ActionType.KEY_PRESS,
            "btn",
            parameters={"key": "enter"},
        )
        result = brush.execute_action(action, timestamp=1000.0)

        assert result.success is True
        key_calls = [
            c for c in platform.calls if c[0] == "key_press"
        ]
        assert len(key_calls) == 1
        assert key_calls[0][1] == ("enter",)

    def test_events_from_both_phases_combined(self) -> None:
        """BrushActionResult.events includes nav + action events."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        brush, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        action = _make_action(ActionType.CLICK, "btn")
        result = brush.execute_action(action, timestamp=1000.0)

        assert result.success is True
        # The combined events list should include both navigation
        # events (ZONE_ENTER) and action events (ZONE_CLICK).
        event_types = {e.type for e in result.events}
        assert SpatialEventType.ZONE_CLICK in event_types

    def test_action_result_reflects_executor(self) -> None:
        """action_result mirrors the ActionExecutor's result."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        brush, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        action = _make_action(ActionType.CLICK, "btn")
        result = brush.execute_action(action, timestamp=1000.0)

        assert result.action_result is not None
        assert result.action_result.action.status == ActionStatus.COMPLETED
        assert result.action_result.action.result == "ok"

    def test_error_from_navigation_propagates(self) -> None:
        """BrushActionResult.error comes from navigation on nav failure."""
        brush, *_ = _build_controller(cursor_pos=(0, 0))

        action = _make_action(ActionType.CLICK, "no_such_zone")
        result = brush.execute_action(action, timestamp=1000.0)

        assert result.success is False
        assert result.error != ""
        assert "not found" in result.error.lower()

    def test_error_from_action_propagates(self) -> None:
        """BrushActionResult.error comes from action on action failure."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        brush, platform, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        # Make click fail after navigation succeeds.
        platform.raise_on = "click"

        action = _make_action(ActionType.CLICK, "btn")
        result = brush.execute_action(action, timestamp=1000.0)

        assert result.success is False
        assert result.action_result is not None
        assert result.action_result.success is False
        assert result.error != ""

    def test_default_timestamp(self) -> None:
        """When timestamp is not provided, a default is used."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        brush, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        before = time.time()
        action = _make_action(ActionType.MOVE, "btn")
        result = brush.execute_action(action)  # no timestamp
        after = time.time()

        assert result.success is True
        assert result.action_result is not None
        ts = result.action_result.action.timestamp
        assert before <= ts <= after


# ------------------------------------------------------------------
# 4. Query Methods
# ------------------------------------------------------------------


class TestBrushController_QueryMethods:
    """Tests for query helper methods."""

    def test_get_current_zone_returns_tracker_zone(self) -> None:
        """get_current_zone() returns the tracker's current zone ID."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, *_ = _build_controller(zones=[zone])

        # Before any update, no zone.
        assert brush.get_current_zone() is None

        # Move into zone.
        brush.update((150, 150), 1.0)
        assert brush.get_current_zone() == "z1"

    def test_get_current_zone_object(self) -> None:
        """get_current_zone_object() returns the Zone from registry."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, *_ = _build_controller(zones=[zone])

        brush.update((150, 150), 1.0)
        zone_obj = brush.get_current_zone_object()

        assert zone_obj is not None
        assert zone_obj.id == "z1"
        assert zone_obj.bounds == zone.bounds

    def test_get_event_history(self) -> None:
        """get_event_history() returns tracker's history."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, *_ = _build_controller(zones=[zone])

        brush.update((150, 150), 1.0)
        brush.update((0, 0), 2.0)

        history = brush.get_event_history()
        assert len(history) >= 2
        # Events should include enter and exit.
        types = [e.type for e in history]
        assert SpatialEventType.ZONE_ENTER in types
        assert SpatialEventType.ZONE_EXIT in types

    def test_get_cursor_pos(self) -> None:
        """get_cursor_pos() returns the platform cursor position."""
        brush, platform, *_ = _build_controller(
            cursor_pos=(42, 99)
        )

        pos = brush.get_cursor_pos()
        assert pos == (42, 99)

    def test_get_zones_at_cursor(self) -> None:
        """get_zones_at_cursor() returns zones from the registry."""
        zone = _make_zone("z1", 0, 0, 200, 200)
        brush, platform, *_ = _build_controller(
            cursor_pos=(100, 100), zones=[zone]
        )

        zones = brush.get_zones_at_cursor()
        assert len(zones) == 1
        assert zones[0].id == "z1"

    def test_zone_count_property(self) -> None:
        """zone_count returns the number of zones in the registry."""
        zones = [
            _make_zone("a", 0, 0, 50, 50),
            _make_zone("b", 100, 100, 50, 50),
            _make_zone("c", 200, 200, 50, 50),
        ]
        brush, *_ = _build_controller(zones=zones)

        assert brush.zone_count == 3


# ------------------------------------------------------------------
# 5. Edge Cases
# ------------------------------------------------------------------


class TestBrushController_EdgeCases:
    """Edge-case tests."""

    def test_empty_registry_navigation_fails(self) -> None:
        """Navigating with no zones in the registry fails."""
        brush, *_ = _build_controller()

        result = brush.navigate_to_zone("anything")
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_zone_removed_between_plan_and_verify(self) -> None:
        """If a zone is removed mid-navigation, brush is lost."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, platform, registry, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[zone]
        )

        # Intercept move_cursor to remove the zone mid-trajectory.
        call_count = 0

        def removing_move(x: int, y: int) -> None:
            nonlocal call_count
            call_count += 1
            # Update the cursor position (important for tracking).
            platform._cursor_pos = (x, y)
            platform.calls.append(("move_cursor", (x, y)))
            # Remove the zone partway through the trajectory.
            if call_count == 1 and registry.contains("z1"):
                registry.remove("z1")

        platform.move_cursor = removing_move  # type: ignore[assignment]

        result = brush.navigate_to_zone("z1")

        # The zone was removed so verification fails => brush lost.
        assert result.success is False
        assert brush.is_brush_lost is True

    def test_repr(self) -> None:
        """__repr__() produces a human-readable string."""
        zone = _make_zone("z1", 100, 100, 200, 100)
        brush, *_ = _build_controller(zones=[zone])

        r = repr(brush)
        assert "BrushController" in r
        assert "brush_lost" in r

    def test_multiple_sequential_navigations(self) -> None:
        """Multiple successive navigations each succeed independently."""
        z1 = _make_zone("z1", 100, 100, 200, 100)
        z2 = _make_zone("z2", 500, 500, 200, 100)
        z3 = _make_zone("z3", 900, 100, 200, 100)
        brush, *_ = _build_controller(
            cursor_pos=(0, 0), zones=[z1, z2, z3]
        )

        r1 = brush.navigate_to_zone("z1")
        assert r1.success is True
        assert brush.get_current_zone() == "z1"

        r2 = brush.navigate_to_zone("z2")
        assert r2.success is True
        assert brush.get_current_zone() == "z2"

        r3 = brush.navigate_to_zone("z3")
        assert r3.success is True
        assert brush.get_current_zone() == "z3"
