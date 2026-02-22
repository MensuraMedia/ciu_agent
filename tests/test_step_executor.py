"""Comprehensive unit tests for ciu_agent.core.step_executor.

Tests cover successful step execution across all action types, action type
mapping, zone-not-found errors, navigation failures, action failures, and
edge cases.  Uses a MockPlatform with cursor-position tracking and real
ZoneRegistry / ZoneTracker / MotionPlanner / ActionExecutor / BrushController
instances (integration-style through the real pipeline).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ciu_agent.config.settings import Settings
from ciu_agent.core.action_executor import ActionExecutor
from ciu_agent.core.brush_controller import BrushController
from ciu_agent.core.motion_planner import MotionPlanner
from ciu_agent.core.step_executor import StepExecutor, StepResult
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.core.zone_tracker import ZoneTracker
from ciu_agent.models.actions import ActionType
from ciu_agent.models.events import SpatialEventType
from ciu_agent.models.task import TaskStep
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


def _make_step(
    step_number: int = 1,
    zone_id: str = "z1",
    zone_label: str = "TestZone",
    action_type: str = "click",
    parameters: dict | None = None,
    expected_change: str = "",
    description: str = "",
) -> TaskStep:
    """Build a ``TaskStep`` with sensible defaults."""
    return TaskStep(
        step_number=step_number,
        zone_id=zone_id,
        zone_label=zone_label,
        action_type=action_type,
        parameters=parameters or {},
        expected_change=expected_change,
        description=description,
    )


def _build_executor(
    cursor_pos: tuple[int, int] = (200, 150),
    zones: list[Zone] | None = None,
    settings: Settings | None = None,
) -> tuple[
    StepExecutor,
    BrushController,
    MockPlatform,
    ZoneRegistry,
]:
    """Construct a full StepExecutor stack with a MockPlatform.

    By default the cursor starts at (200, 150) which is the center of
    the default zone (x=100, y=100, w=200, h=100), so navigation
    succeeds immediately.

    Returns the executor and key sub-components for direct access.
    """
    platform = MockPlatform(cursor_pos=cursor_pos)
    registry = ZoneRegistry()
    if zones:
        registry.register_many(zones)

    s = settings or Settings()
    tracker = ZoneTracker(registry, s)
    planner = MotionPlanner(registry, s)
    action_executor = ActionExecutor(platform, registry, s)

    brush = BrushController(
        platform=platform,
        registry=registry,
        tracker=tracker,
        planner=planner,
        executor=action_executor,
        settings=s,
    )

    executor = StepExecutor(brush, registry, platform, s)
    return executor, brush, platform, registry


# ------------------------------------------------------------------
# 1. Successful Step Execution
# ------------------------------------------------------------------


class TestStepExecutor_SuccessfulExecution:
    """Tests for successful step execution across all action types."""

    def test_click_step_succeeds(self) -> None:
        """A click step targeting a registered zone succeeds."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=1000.0)

        assert isinstance(result, StepResult)
        assert result.success is True

    def test_type_text_step_succeeds(self) -> None:
        """A type_text step with text parameter succeeds."""
        zone = _make_zone(
            "field", 100, 100, 200, 100,
            zone_type=ZoneType.TEXT_FIELD,
        )
        executor, _, platform, _ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="field",
            action_type="type_text",
            parameters={"text": "hello world"},
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        type_calls = [
            c for c in platform.calls if c[0] == "type_text"
        ]
        assert len(type_calls) == 1
        assert type_calls[0][1] == ("hello world",)

    def test_key_press_step_succeeds(self) -> None:
        """A key_press step with key parameter succeeds."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="btn",
            action_type="key_press",
            parameters={"key": "enter"},
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        key_calls = [
            c for c in platform.calls if c[0] == "key_press"
        ]
        assert len(key_calls) == 1
        assert key_calls[0][1] == ("enter",)

    def test_scroll_step_succeeds(self) -> None:
        """A scroll step targeting a zone succeeds."""
        zone = _make_zone(
            "scrollable", 100, 100, 200, 100,
            zone_type=ZoneType.SCROLL_AREA,
        )
        executor, _, platform, _ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="scrollable",
            action_type="scroll",
            parameters={"direction": "down", "amount": 5},
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        scroll_calls = [
            c for c in platform.calls if c[0] == "scroll"
        ]
        assert len(scroll_calls) == 1

    def test_move_step_succeeds(self) -> None:
        """A move step navigates to the zone without additional action."""
        zone = _make_zone("target", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="target",
            action_type="move",
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        # No click, type_text, or key_press calls should appear.
        non_move = [
            c for c in platform.calls
            if c[0] in ("click", "type_text", "key_press")
        ]
        assert len(non_move) == 0

    def test_double_click_step_succeeds(self) -> None:
        """A double_click step succeeds."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="btn",
            action_type="double_click",
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        dbl_calls = [
            c for c in platform.calls if c[0] == "double_click"
        ]
        assert len(dbl_calls) == 1

    def test_success_result_has_empty_error(self) -> None:
        """On success, StepResult.error is an empty string."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        assert result.error == ""

    def test_success_result_has_empty_error_type(self) -> None:
        """On success, StepResult.error_type is an empty string."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        assert result.error_type == ""


# ------------------------------------------------------------------
# 2. Action Type Mapping
# ------------------------------------------------------------------


class TestStepExecutor_ActionTypeMapping:
    """Tests that action_type strings map to correct ActionType enums."""

    def test_click_maps_to_action_type_click(self) -> None:
        """'click' string maps to ActionType.CLICK."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        assert result.action_result is not None
        assert result.action_result.action_result is not None
        assert (
            result.action_result.action_result.action.type
            == ActionType.CLICK
        )

    def test_type_text_maps_to_action_type_type_text(self) -> None:
        """'type_text' string maps to ActionType.TYPE_TEXT."""
        zone = _make_zone(
            "field", 100, 100, 200, 100,
            zone_type=ZoneType.TEXT_FIELD,
        )
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="field",
            action_type="type_text",
            parameters={"text": "test"},
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        assert result.action_result is not None
        assert result.action_result.action_result is not None
        assert (
            result.action_result.action_result.action.type
            == ActionType.TYPE_TEXT
        )

    def test_key_press_maps_to_action_type_key_press(self) -> None:
        """'key_press' string maps to ActionType.KEY_PRESS."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="btn",
            action_type="key_press",
            parameters={"key": "tab"},
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        assert result.action_result is not None
        assert result.action_result.action_result is not None
        assert (
            result.action_result.action_result.action.type
            == ActionType.KEY_PRESS
        )

    def test_scroll_maps_to_action_type_scroll(self) -> None:
        """'scroll' string maps to ActionType.SCROLL."""
        zone = _make_zone("area", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="area",
            action_type="scroll",
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        assert result.action_result is not None
        assert result.action_result.action_result is not None
        assert (
            result.action_result.action_result.action.type
            == ActionType.SCROLL
        )

    def test_move_maps_to_action_type_move(self) -> None:
        """'move' string maps to ActionType.MOVE."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="btn",
            action_type="move",
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True
        assert result.action_result is not None
        assert result.action_result.action_result is not None
        assert (
            result.action_result.action_result.action.type
            == ActionType.MOVE
        )

    def test_unknown_action_type_returns_action_failed(self) -> None:
        """An unrecognised action_type string yields error_type='action_failed'."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="btn",
            action_type="teleport",
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is False
        assert result.error_type == "action_failed"
        assert "teleport" in result.error.lower()
        assert result.action_result is None


# ------------------------------------------------------------------
# 3. Zone Not Found
# ------------------------------------------------------------------


class TestStepExecutor_ZoneNotFound:
    """Tests for steps targeting zones that are not in the registry."""

    def test_missing_zone_returns_zone_not_found(self) -> None:
        """Zone not in registry results in error_type='zone_not_found'."""
        zone = _make_zone("existing", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="nonexistent",
            action_type="click",
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is False
        assert result.error_type == "zone_not_found"

    def test_zone_not_found_error_contains_zone_id(self) -> None:
        """Error message includes the missing zone ID."""
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[]
        )

        step = _make_step(
            zone_id="btn_save_42",
            action_type="click",
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is False
        assert "btn_save_42" in result.error

    def test_zone_not_found_action_result_is_none(self) -> None:
        """When zone is missing, action_result is None."""
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[]
        )

        step = _make_step(
            zone_id="missing",
            action_type="click",
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.action_result is None

    def test_zone_not_found_success_is_false(self) -> None:
        """When zone is missing, success is False."""
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[]
        )

        step = _make_step(
            zone_id="gone",
            action_type="move",
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is False


# ------------------------------------------------------------------
# 4. Navigation Failure
# ------------------------------------------------------------------


class TestStepExecutor_NavigationFailure:
    """Tests for steps where navigation to the zone fails (brush lost)."""

    def test_navigation_failure_yields_brush_lost(self) -> None:
        """When navigation fails, error_type is 'brush_lost'."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(0, 0), zones=[zone]
        )

        # Break move_cursor so cursor stays at (0, 0) -- outside zone.
        def broken_move(x: int, y: int) -> None:
            platform.calls.append(("move_cursor", (x, y)))

        platform.move_cursor = broken_move  # type: ignore[assignment]

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is False
        assert result.error_type == "brush_lost"

    def test_navigation_failure_success_is_false(self) -> None:
        """StepResult.success is False when navigation fails."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(0, 0), zones=[zone]
        )

        platform.move_cursor = lambda x, y: platform.calls.append(  # type: ignore[assignment]
            ("move_cursor", (x, y))
        )

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is False

    def test_navigation_failure_preserves_events(self) -> None:
        """Events from the navigation attempt are preserved."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(0, 0), zones=[zone]
        )

        platform.move_cursor = lambda x, y: platform.calls.append(  # type: ignore[assignment]
            ("move_cursor", (x, y))
        )

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=1000.0)

        # Navigation failure should produce a BRUSH_LOST event.
        assert result.action_result is not None
        assert isinstance(result.events, list)
        brush_lost_events = [
            e for e in result.events
            if e.type == SpatialEventType.BRUSH_LOST
        ]
        assert len(brush_lost_events) >= 1

    def test_navigation_failure_has_error_message(self) -> None:
        """Navigation failure produces a non-empty error message."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(0, 0), zones=[zone]
        )

        platform.move_cursor = lambda x, y: platform.calls.append(  # type: ignore[assignment]
            ("move_cursor", (x, y))
        )

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=1000.0)

        assert result.error != ""


# ------------------------------------------------------------------
# 5. Action Failure
# ------------------------------------------------------------------


class TestStepExecutor_ActionFailure:
    """Tests for steps where the action itself fails after navigation."""

    def test_platform_exception_yields_action_failed(self) -> None:
        """A platform exception during click produces error_type='action_failed'."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        # Navigation will succeed (cursor is at zone center).
        # Make click fail.
        platform.raise_on = "click"

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is False
        assert result.error_type == "action_failed"

    def test_action_failure_success_is_false(self) -> None:
        """StepResult.success is False when the action fails."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        platform.raise_on = "type_text"

        step = _make_step(
            zone_id="btn",
            action_type="type_text",
            parameters={"text": "boom"},
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is False

    def test_action_failure_error_propagated(self) -> None:
        """Error message from the platform propagates to StepResult."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        platform.raise_on = "click"

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=1000.0)

        assert result.error != ""
        assert "forced error" in result.error.lower()

    def test_action_failure_has_action_result(self) -> None:
        """When the action fails, action_result is not None."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, _, platform, _ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        platform.raise_on = "double_click"

        step = _make_step(
            zone_id="btn",
            action_type="double_click",
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is False
        assert result.action_result is not None


# ------------------------------------------------------------------
# 6. Edge Cases
# ------------------------------------------------------------------


class TestStepExecutor_EdgeCases:
    """Edge-case tests for StepExecutor."""

    def test_step_with_empty_parameters(self) -> None:
        """A step with an empty parameters dict still works."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            zone_id="btn",
            action_type="click",
            parameters={},
        )
        result = executor.execute(step, timestamp=1000.0)

        assert result.success is True

    def test_step_result_timestamp_matches_input(self) -> None:
        """StepResult.timestamp matches the timestamp passed to execute."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(zone_id="btn", action_type="click")
        result = executor.execute(step, timestamp=42.5)

        assert result.timestamp == 42.5

    def test_step_executor_repr(self) -> None:
        """StepExecutor repr produces a human-readable string."""
        zone = _make_zone("btn", 100, 100, 200, 100)
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        r = repr(executor)
        assert "StepExecutor" in r
        assert "zones=" in r

    def test_step_with_all_parameters_specified(self) -> None:
        """A step with all optional parameters still works correctly."""
        zone = _make_zone(
            "field", 100, 100, 200, 100,
            zone_type=ZoneType.TEXT_FIELD,
        )
        executor, *_ = _build_executor(
            cursor_pos=(200, 150), zones=[zone]
        )

        step = _make_step(
            step_number=7,
            zone_id="field",
            zone_label="Username Input",
            action_type="type_text",
            parameters={"text": "admin"},
            expected_change="username field populated",
            description="Enter the username",
        )
        result = executor.execute(step, timestamp=9999.0)

        assert result.success is True
        assert result.step.step_number == 7
        assert result.step.zone_label == "Username Input"
        assert result.step.expected_change == "username field populated"
        assert result.step.description == "Enter the username"
        assert result.timestamp == 9999.0
