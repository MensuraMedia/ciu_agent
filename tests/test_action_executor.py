"""Comprehensive unit tests for ciu_agent.core.action_executor.

Covers click actions, text typing, key presses, scrolling,
zone verification, move/drag, and edge cases.  Uses a hand-rolled
MockPlatform for clarity and controllability rather than
unittest.mock.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from ciu_agent.config.settings import Settings
from ciu_agent.core.action_executor import ActionExecutor
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.actions import Action, ActionStatus, ActionType
from ciu_agent.models.events import SpatialEventType
from ciu_agent.models.zone import Rectangle, Zone, ZoneState, ZoneType
from ciu_agent.platform.interface import PlatformInterface, WindowInfo

# ------------------------------------------------------------------
# MockPlatform
# ------------------------------------------------------------------


class MockPlatform(PlatformInterface):
    """Controllable fake platform for testing ActionExecutor.

    Records every method call and returns canned values.
    Set ``raise_on_*`` attributes to force specific methods to
    raise exceptions so that error-handling paths can be exercised.
    """

    def __init__(self, cursor_pos: tuple[int, int] = (50, 25)) -> None:
        self._cursor_pos: tuple[int, int] = cursor_pos

        # Call recorders
        self.click_calls: list[tuple[int, int, str]] = []
        self.double_click_calls: list[tuple[int, int, str]] = []
        self.type_calls: list[str] = []
        self.key_press_calls: list[str] = []
        self.scroll_calls: list[tuple[int, int, int]] = []
        self.move_cursor_calls: list[tuple[int, int]] = []

        # Exception triggers (set to an Exception instance to raise)
        self.raise_on_click: Exception | None = None
        self.raise_on_double_click: Exception | None = None
        self.raise_on_type_text: Exception | None = None
        self.raise_on_key_press: Exception | None = None
        self.raise_on_scroll: Exception | None = None
        self.raise_on_move_cursor: Exception | None = None

    # -- Screen capture (not used by executor) ---------------------

    def capture_frame(self) -> NDArray[np.uint8]:
        return np.zeros((100, 100, 3), dtype=np.uint8)

    # -- Cursor ----------------------------------------------------

    def get_cursor_pos(self) -> tuple[int, int]:
        return self._cursor_pos

    def move_cursor(self, x: int, y: int) -> None:
        if self.raise_on_move_cursor is not None:
            raise self.raise_on_move_cursor
        self.move_cursor_calls.append((x, y))
        self._cursor_pos = (x, y)

    # -- Mouse actions ---------------------------------------------

    def click(self, x: int, y: int, button: str = "left") -> None:
        if self.raise_on_click is not None:
            raise self.raise_on_click
        self.click_calls.append((x, y, button))

    def double_click(
        self, x: int, y: int, button: str = "left"
    ) -> None:
        if self.raise_on_double_click is not None:
            raise self.raise_on_double_click
        self.double_click_calls.append((x, y, button))

    def scroll(self, x: int, y: int, amount: int) -> None:
        if self.raise_on_scroll is not None:
            raise self.raise_on_scroll
        self.scroll_calls.append((x, y, amount))

    # -- Keyboard --------------------------------------------------

    def type_text(self, text: str) -> None:
        if self.raise_on_type_text is not None:
            raise self.raise_on_type_text
        self.type_calls.append(text)

    def key_press(self, key: str) -> None:
        if self.raise_on_key_press is not None:
            raise self.raise_on_key_press
        self.key_press_calls.append(key)

    # -- Screen & window queries -----------------------------------

    def get_screen_size(self) -> tuple[int, int]:
        return (1920, 1080)

    def get_active_window(self) -> WindowInfo:
        return WindowInfo(
            title="Mock Window",
            x=0,
            y=0,
            width=800,
            height=600,
            is_active=True,
            process_name="mock",
        )

    def list_windows(self) -> list[WindowInfo]:
        return [self.get_active_window()]

    def get_platform_name(self) -> str:
        return "mock"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_zone(
    zone_id: str = "z1",
    x: int = 0,
    y: int = 0,
    width: int = 100,
    height: int = 50,
    zone_type: ZoneType = ZoneType.BUTTON,
    label: str = "OK",
    state: ZoneState = ZoneState.ENABLED,
    confidence: float = 0.9,
    last_seen: float = 1000.0,
    parent_id: str | None = None,
) -> Zone:
    """Shorthand factory for building Zone instances in tests."""
    return Zone(
        id=zone_id,
        bounds=Rectangle(x=x, y=y, width=width, height=height),
        type=zone_type,
        label=label,
        state=state,
        confidence=confidence,
        last_seen=last_seen,
        parent_id=parent_id,
    )


def _make_action(
    action_type: ActionType = ActionType.CLICK,
    target_zone_id: str = "z1",
    parameters: dict | None = None,
) -> Action:
    """Shorthand factory for building Action instances in tests."""
    return Action(
        type=action_type,
        target_zone_id=target_zone_id,
        status=ActionStatus.PENDING,
        parameters=parameters if parameters is not None else {},
        timestamp=0.0,
        result="",
    )


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def platform() -> MockPlatform:
    """Return a MockPlatform with the cursor at zone center (50, 25)."""
    return MockPlatform(cursor_pos=(50, 25))


@pytest.fixture()
def registry() -> ZoneRegistry:
    """Return a ZoneRegistry pre-loaded with a single zone at (0,0,100,50)."""
    reg = ZoneRegistry()
    reg.register(_make_zone("z1", x=0, y=0, width=100, height=50))
    return reg


@pytest.fixture()
def settings() -> Settings:
    """Return default Settings."""
    return Settings()


@pytest.fixture()
def executor(
    platform: MockPlatform,
    registry: ZoneRegistry,
    settings: Settings,
) -> ActionExecutor:
    """Return an ActionExecutor wired to the mock platform."""
    return ActionExecutor(platform, registry, settings)


# ==================================================================
# 1. Click Actions
# ==================================================================


class TestClickActions:
    """Tests for ActionType.CLICK handling."""

    def test_successful_left_click(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """A basic left-click action should succeed."""
        action = _make_action(ActionType.CLICK, "z1")
        result = executor.execute(action, timestamp=1.0)

        assert result.success is True
        assert result.action.status is ActionStatus.COMPLETED
        assert len(platform.click_calls) == 1

    def test_zone_click_event_emitted_with_left_button(
        self,
        executor: ActionExecutor,
    ) -> None:
        """A ZONE_CLICK event should be emitted with button='left'."""
        action = _make_action(ActionType.CLICK, "z1")
        result = executor.execute(action, timestamp=1.0)

        assert len(result.events) == 1
        event = result.events[0]
        assert event.type is SpatialEventType.ZONE_CLICK
        assert event.zone_id == "z1"
        assert event.data["button"] == "left"

    def test_right_click_passes_button_through(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """Right-click should forward button='right' to the platform."""
        action = _make_action(
            ActionType.CLICK, "z1", {"button": "right"}
        )
        result = executor.execute(action, timestamp=1.0)

        assert result.success is True
        assert platform.click_calls[0][2] == "right"
        assert result.events[0].data["button"] == "right"

    def test_click_at_zone_center_by_default(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """Without explicit coords, click should target zone center."""
        action = _make_action(ActionType.CLICK, "z1")
        executor.execute(action, timestamp=1.0)

        # Zone is (0, 0, 100, 50), center = (50, 25)
        assert platform.click_calls[0][:2] == (50, 25)

    def test_click_at_custom_coordinates(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """Explicit x/y in parameters should override zone center."""
        action = _make_action(
            ActionType.CLICK, "z1", {"x": 10, "y": 5}
        )
        executor.execute(action, timestamp=1.0)

        assert platform.click_calls[0][:2] == (10, 5)

    def test_platform_exception_produces_failed_result(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """An OS-level exception during click should yield FAILED."""
        platform.raise_on_click = RuntimeError("input blocked")
        action = _make_action(ActionType.CLICK, "z1")
        result = executor.execute(action, timestamp=1.0)

        assert result.success is False
        assert result.action.status is ActionStatus.FAILED
        assert "input blocked" in result.error

    def test_action_status_set_to_completed_on_success(
        self,
        executor: ActionExecutor,
    ) -> None:
        """Successful click should set action status to COMPLETED."""
        action = _make_action(ActionType.CLICK, "z1")
        result = executor.execute(action, timestamp=1.0)

        assert result.action.status is ActionStatus.COMPLETED
        assert result.action.result == "ok"

    def test_double_click_emits_event_with_double_true(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """Double-click should emit ZONE_CLICK with double=True."""
        action = _make_action(ActionType.DOUBLE_CLICK, "z1")
        result = executor.execute(action, timestamp=1.0)

        assert result.success is True
        assert len(platform.double_click_calls) == 1
        event = result.events[0]
        assert event.type is SpatialEventType.ZONE_CLICK
        assert event.data["double"] is True
        assert event.data["button"] == "left"


# ==================================================================
# 2. Type Text Actions
# ==================================================================


class TestTypeTextActions:
    """Tests for ActionType.TYPE_TEXT handling."""

    def test_successful_type_text(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """Typing text with a valid 'text' parameter should succeed."""
        action = _make_action(
            ActionType.TYPE_TEXT, "z1", {"text": "hello world"}
        )
        result = executor.execute(action, timestamp=2.0)

        assert result.success is True
        assert platform.type_calls == ["hello world"]

    def test_zone_type_event_emitted_with_text(
        self,
        executor: ActionExecutor,
    ) -> None:
        """A ZONE_TYPE event should carry the typed text."""
        action = _make_action(
            ActionType.TYPE_TEXT, "z1", {"text": "abc"}
        )
        result = executor.execute(action, timestamp=2.0)

        assert len(result.events) == 1
        event = result.events[0]
        assert event.type is SpatialEventType.ZONE_TYPE
        assert event.zone_id == "z1"
        assert event.data["text"] == "abc"

    def test_missing_text_parameter_fails(
        self,
        executor: ActionExecutor,
    ) -> None:
        """TYPE_TEXT without 'text' in parameters should FAIL."""
        action = _make_action(ActionType.TYPE_TEXT, "z1", {})
        result = executor.execute(action, timestamp=2.0)

        assert result.success is False
        assert result.action.status is ActionStatus.FAILED
        assert "missing required parameter 'text'" in result.error

    def test_platform_exception_on_type_text(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """A platform error during typing should yield FAILED."""
        platform.raise_on_type_text = OSError("keyboard locked")
        action = _make_action(
            ActionType.TYPE_TEXT, "z1", {"text": "test"}
        )
        result = executor.execute(action, timestamp=2.0)

        assert result.success is False
        assert "keyboard locked" in result.error

    def test_empty_text_string_is_valid(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """An empty string is a valid text value (no-op type)."""
        action = _make_action(
            ActionType.TYPE_TEXT, "z1", {"text": ""}
        )
        result = executor.execute(action, timestamp=2.0)

        assert result.success is True
        assert platform.type_calls == [""]

    def test_action_status_lifecycle(
        self,
        executor: ActionExecutor,
    ) -> None:
        """Action should transition PENDING -> IN_PROGRESS -> COMPLETED.

        We verify the initial status is PENDING and the final result
        has COMPLETED.  The IN_PROGRESS state is set internally before
        the handler runs.
        """
        action = _make_action(ActionType.TYPE_TEXT, "z1", {"text": "x"})
        assert action.status is ActionStatus.PENDING

        result = executor.execute(action, timestamp=2.0)
        assert result.action.status is ActionStatus.COMPLETED


# ==================================================================
# 3. Key Press Actions
# ==================================================================


class TestKeyPressActions:
    """Tests for ActionType.KEY_PRESS handling."""

    def test_successful_key_press(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """A key press with 'key' parameter should succeed."""
        action = _make_action(
            ActionType.KEY_PRESS, "z1", {"key": "enter"}
        )
        result = executor.execute(action, timestamp=3.0)

        assert result.success is True
        assert platform.key_press_calls == ["enter"]
        assert result.action.status is ActionStatus.COMPLETED

    def test_missing_key_parameter_fails(
        self,
        executor: ActionExecutor,
    ) -> None:
        """KEY_PRESS without 'key' should FAIL."""
        action = _make_action(ActionType.KEY_PRESS, "z1", {})
        result = executor.execute(action, timestamp=3.0)

        assert result.success is False
        assert "missing required parameter 'key'" in result.error

    def test_key_combo_passed_through(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """A key combo string like 'ctrl+s' is forwarded as-is."""
        action = _make_action(
            ActionType.KEY_PRESS, "z1", {"key": "ctrl+s"}
        )
        result = executor.execute(action, timestamp=3.0)

        assert result.success is True
        assert platform.key_press_calls == ["ctrl+s"]

    def test_no_spatial_event_for_key_press(
        self,
        executor: ActionExecutor,
    ) -> None:
        """Key press should not emit any spatial events."""
        action = _make_action(
            ActionType.KEY_PRESS, "z1", {"key": "tab"}
        )
        result = executor.execute(action, timestamp=3.0)

        assert result.events == []


# ==================================================================
# 4. Scroll Actions
# ==================================================================


class TestScrollActions:
    """Tests for ActionType.SCROLL handling."""

    def test_scroll_down_with_default_amount(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """Default scroll should be 3 increments downward (negative)."""
        action = _make_action(ActionType.SCROLL, "z1")
        result = executor.execute(action, timestamp=4.0)

        assert result.success is True
        # Zone center = (50, 25); default direction=down, amount=3
        # signed_amount = -3
        assert platform.scroll_calls == [(50, 25, -3)]

    def test_scroll_up_reverses_sign(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """Scrolling up should produce a positive scroll amount."""
        action = _make_action(
            ActionType.SCROLL, "z1", {"direction": "up", "amount": 5}
        )
        result = executor.execute(action, timestamp=4.0)

        assert result.success is True
        assert platform.scroll_calls == [(50, 25, 5)]

    def test_custom_scroll_amount(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """A custom amount should be passed to the platform."""
        action = _make_action(
            ActionType.SCROLL, "z1", {"amount": 10, "direction": "down"}
        )
        executor.execute(action, timestamp=4.0)

        assert platform.scroll_calls == [(50, 25, -10)]

    def test_scroll_at_zone_center_coordinates(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
        registry: ZoneRegistry,
    ) -> None:
        """Scroll coords should be the zone center, not cursor pos."""
        # Register a zone with a different center
        registry.register(
            _make_zone("z2", x=200, y=100, width=60, height=40)
        )
        # Move cursor inside z2
        platform._cursor_pos = (230, 120)

        action = _make_action(ActionType.SCROLL, "z2")
        executor.execute(action, timestamp=4.0)

        # Zone z2 center = (200 + 30, 100 + 20) = (230, 120)
        assert platform.scroll_calls[0][:2] == (230, 120)


# ==================================================================
# 5. Zone Verification
# ==================================================================


class TestZoneVerification:
    """Tests for zone lookup and cursor-in-zone checks."""

    def test_cursor_inside_zone_proceeds(
        self,
        executor: ActionExecutor,
    ) -> None:
        """Action proceeds when cursor is within the target zone."""
        action = _make_action(ActionType.CLICK, "z1")
        result = executor.execute(action, timestamp=5.0)

        assert result.success is True

    def test_cursor_outside_zone_fails(
        self,
        platform: MockPlatform,
        registry: ZoneRegistry,
        settings: Settings,
    ) -> None:
        """Action fails when cursor is outside the target zone."""
        platform._cursor_pos = (999, 999)
        executor = ActionExecutor(platform, registry, settings)

        action = _make_action(ActionType.CLICK, "z1")
        result = executor.execute(action, timestamp=5.0)

        assert result.success is False
        assert result.action.status is ActionStatus.FAILED
        assert "cursor not in target zone" in result.error

    def test_target_zone_not_in_registry_fails(
        self,
        executor: ActionExecutor,
    ) -> None:
        """Action fails when the target zone ID is not registered."""
        action = _make_action(ActionType.CLICK, "nonexistent_zone")
        result = executor.execute(action, timestamp=5.0)

        assert result.success is False
        assert result.action.status is ActionStatus.FAILED
        assert "not found in registry" in result.error

    def test_zone_not_found_includes_zone_id_in_error(
        self,
        executor: ActionExecutor,
    ) -> None:
        """The error message should include the missing zone ID."""
        action = _make_action(ActionType.CLICK, "phantom_42")
        result = executor.execute(action, timestamp=5.0)

        assert "phantom_42" in result.error

    def test_disabled_zone_state_does_not_block_execution(
        self,
        platform: MockPlatform,
        settings: Settings,
    ) -> None:
        """Executor doesn't check zone state -- disabled zones still execute."""
        reg = ZoneRegistry()
        reg.register(
            _make_zone(
                "z_disabled",
                x=0, y=0, width=100, height=50,
                state=ZoneState.DISABLED,
            )
        )
        platform._cursor_pos = (50, 25)
        executor = ActionExecutor(platform, reg, settings)

        action = _make_action(ActionType.CLICK, "z_disabled")
        result = executor.execute(action, timestamp=5.0)

        assert result.success is True

    def test_zone_state_focused_does_not_affect_execution(
        self,
        platform: MockPlatform,
        settings: Settings,
    ) -> None:
        """Focused zone state is irrelevant to the executor."""
        reg = ZoneRegistry()
        reg.register(
            _make_zone(
                "z_focused",
                x=0, y=0, width=100, height=50,
                state=ZoneState.FOCUSED,
            )
        )
        platform._cursor_pos = (50, 25)
        executor = ActionExecutor(platform, reg, settings)

        action = _make_action(ActionType.TYPE_TEXT, "z_focused", {"text": "hi"})
        result = executor.execute(action, timestamp=5.0)

        assert result.success is True


# ==================================================================
# 6. Move and Drag
# ==================================================================


class TestMoveAndDrag:
    """Tests for ActionType.MOVE and ActionType.DRAG."""

    def test_move_calls_platform_move_cursor_to_zone_center(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """MOVE action should call platform.move_cursor to zone center."""
        action = _make_action(ActionType.MOVE, "z1")
        result = executor.execute(action, timestamp=6.0)

        assert result.success is True
        # Zone center = (50, 25)
        assert platform.move_cursor_calls == [(50, 25)]

    def test_move_success_result(
        self,
        executor: ActionExecutor,
    ) -> None:
        """MOVE should produce a successful result with COMPLETED status."""
        action = _make_action(ActionType.MOVE, "z1")
        result = executor.execute(action, timestamp=6.0)

        assert result.success is True
        assert result.action.status is ActionStatus.COMPLETED
        assert result.error == ""

    def test_drag_returns_success_placeholder(
        self,
        executor: ActionExecutor,
    ) -> None:
        """DRAG is a placeholder that returns success."""
        action = _make_action(ActionType.DRAG, "z1")
        result = executor.execute(action, timestamp=6.0)

        assert result.success is True
        assert result.action.status is ActionStatus.COMPLETED

    def test_move_platform_exception_fails(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """A platform error during move should yield FAILED."""
        platform.raise_on_move_cursor = RuntimeError("cursor stuck")
        action = _make_action(ActionType.MOVE, "z1")
        result = executor.execute(action, timestamp=6.0)

        assert result.success is False
        assert "cursor stuck" in result.error


# ==================================================================
# 7. Edge Cases
# ==================================================================


class TestEdgeCases:
    """Miscellaneous edge-case and structural tests."""

    def test_click_and_double_click_produce_one_event_each(
        self,
        executor: ActionExecutor,
    ) -> None:
        """Both click variants emit exactly one spatial event."""
        click_result = executor.execute(
            _make_action(ActionType.CLICK, "z1"), timestamp=7.0
        )
        dc_result = executor.execute(
            _make_action(ActionType.DOUBLE_CLICK, "z1"), timestamp=7.1
        )

        assert len(click_result.events) == 1
        assert len(dc_result.events) == 1

    def test_action_result_error_is_empty_on_success(
        self,
        executor: ActionExecutor,
    ) -> None:
        """ActionResult.error should be an empty string on success."""
        action = _make_action(ActionType.CLICK, "z1")
        result = executor.execute(action, timestamp=7.0)

        assert result.error == ""

    def test_action_result_timestamp_matches_input(
        self,
        executor: ActionExecutor,
    ) -> None:
        """The ActionResult.timestamp should match the provided value."""
        ts = 123456.789
        action = _make_action(ActionType.CLICK, "z1")
        result = executor.execute(action, timestamp=ts)

        assert result.timestamp == ts
        assert result.action.timestamp == ts

    def test_action_with_no_parameters_uses_defaults(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """An action with empty parameters falls back to defaults.

        For CLICK: button defaults to 'left', position defaults to
        zone center.
        """
        action = _make_action(ActionType.CLICK, "z1", {})
        result = executor.execute(action, timestamp=7.0)

        assert result.success is True
        assert platform.click_calls[0] == (50, 25, "left")

    def test_failed_action_has_non_empty_error(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """Failed results should always carry a descriptive error."""
        platform.raise_on_click = ValueError("unexpected state")
        action = _make_action(ActionType.CLICK, "z1")
        result = executor.execute(action, timestamp=7.0)

        assert result.success is False
        assert len(result.error) > 0

    def test_type_text_event_position_is_zone_center(
        self,
        executor: ActionExecutor,
    ) -> None:
        """ZONE_TYPE event position should be the zone center."""
        action = _make_action(
            ActionType.TYPE_TEXT, "z1", {"text": "pos"}
        )
        result = executor.execute(action, timestamp=7.0)

        event = result.events[0]
        assert event.position == (50, 25)

    def test_scroll_platform_exception_fails(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """A platform error during scroll should yield FAILED."""
        platform.raise_on_scroll = RuntimeError("scroll hw error")
        action = _make_action(ActionType.SCROLL, "z1")
        result = executor.execute(action, timestamp=7.0)

        assert result.success is False
        assert "scroll hw error" in result.error

    def test_double_click_platform_exception_fails(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """A platform error during double-click should yield FAILED."""
        platform.raise_on_double_click = OSError("double click blocked")
        action = _make_action(ActionType.DOUBLE_CLICK, "z1")
        result = executor.execute(action, timestamp=7.0)

        assert result.success is False
        assert "double click blocked" in result.error

    def test_key_press_platform_exception_fails(
        self,
        executor: ActionExecutor,
        platform: MockPlatform,
    ) -> None:
        """A platform error during key press should yield FAILED."""
        platform.raise_on_key_press = RuntimeError("key hw error")
        action = _make_action(
            ActionType.KEY_PRESS, "z1", {"key": "enter"}
        )
        result = executor.execute(action, timestamp=7.0)

        assert result.success is False
        assert "key hw error" in result.error

    def test_click_event_position_matches_click_point(
        self,
        executor: ActionExecutor,
    ) -> None:
        """The ZONE_CLICK event position should match the click point."""
        action = _make_action(
            ActionType.CLICK, "z1", {"x": 30, "y": 10}
        )
        result = executor.execute(action, timestamp=7.0)

        event = result.events[0]
        assert event.position == (30, 10)

    def test_click_event_timestamp_matches(
        self,
        executor: ActionExecutor,
    ) -> None:
        """The emitted event timestamp should match execution timestamp."""
        ts = 42.0
        action = _make_action(ActionType.CLICK, "z1")
        result = executor.execute(action, timestamp=ts)

        assert result.events[0].timestamp == ts

    def test_original_action_is_not_mutated(
        self,
        executor: ActionExecutor,
    ) -> None:
        """The original Action object should remain unchanged.

        The executor uses dataclasses.replace, so the original stays
        PENDING.
        """
        action = _make_action(ActionType.CLICK, "z1")
        executor.execute(action, timestamp=7.0)

        assert action.status is ActionStatus.PENDING
        assert action.result == ""
