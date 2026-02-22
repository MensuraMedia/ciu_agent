"""Comprehensive unit tests for ciu_agent.core.zone_tracker.ZoneTracker.

Covers zone enter/exit events, hover detection, query methods,
reset behaviour, and edge cases.
"""

from __future__ import annotations

import pytest

from ciu_agent.config.settings import Settings
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.core.zone_tracker import ZoneTracker
from ciu_agent.models.events import SpatialEvent, SpatialEventType
from ciu_agent.models.zone import Rectangle, Zone, ZoneState, ZoneType

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


@pytest.fixture()
def registry() -> ZoneRegistry:
    """Return a fresh empty ZoneRegistry for each test."""
    return ZoneRegistry()


@pytest.fixture()
def settings() -> Settings:
    """Return default Settings (hover_threshold_ms=300)."""
    return Settings()


@pytest.fixture()
def custom_settings() -> Settings:
    """Return Settings with a shorter hover threshold for faster tests."""
    return Settings(hover_threshold_ms=100)


@pytest.fixture()
def zone_a() -> Zone:
    """A button at (10, 10) with size 80x30."""
    return _make_zone("zone_a", 10, 10, 80, 30, ZoneType.BUTTON, "Save")


@pytest.fixture()
def zone_b() -> Zone:
    """A button at (200, 200) with size 80x30."""
    return _make_zone("zone_b", 200, 200, 80, 30, ZoneType.BUTTON, "Cancel")


@pytest.fixture()
def tracker(registry: ZoneRegistry, settings: Settings) -> ZoneTracker:
    """Return a ZoneTracker with an empty registry and default settings."""
    return ZoneTracker(registry, settings)


# ==================================================================
# Zone Enter / Exit Events
# ==================================================================


class TestZoneEnterExit:
    """Tests for zone enter and exit event emission."""

    def test_cursor_enters_zone_emits_zone_enter(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Cursor entering a zone produces a ZONE_ENTER event."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        events = tracker.update((50, 25), 1.0)

        assert len(events) == 1
        assert events[0].type is SpatialEventType.ZONE_ENTER
        assert events[0].zone_id == "zone_a"
        assert events[0].position == (50, 25)
        assert events[0].timestamp == 1.0

    def test_cursor_exits_zone_emits_zone_exit_with_duration(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Cursor leaving a zone produces a ZONE_EXIT with duration data."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)  # enter zone_a
        events = tracker.update((500, 500), 2.5)  # exit to empty space

        assert len(events) == 1
        assert events[0].type is SpatialEventType.ZONE_EXIT
        assert events[0].zone_id == "zone_a"
        assert events[0].data["duration"] == pytest.approx(1.5)

    def test_cursor_moves_zone_a_to_zone_b_emits_exit_then_enter(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
        zone_b: Zone,
    ) -> None:
        """Moving from zone A to zone B emits EXIT(A) then ENTER(B)."""
        registry.register(zone_a)
        registry.register(zone_b)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)  # enter zone_a
        events = tracker.update((240, 215), 3.0)  # enter zone_b

        assert len(events) == 2
        assert events[0].type is SpatialEventType.ZONE_EXIT
        assert events[0].zone_id == "zone_a"
        assert events[0].data["duration"] == pytest.approx(2.0)
        assert events[1].type is SpatialEventType.ZONE_ENTER
        assert events[1].zone_id == "zone_b"

    def test_cursor_moves_zone_to_empty_space_emits_exit_only(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Moving from a zone to empty space emits only EXIT."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)  # enter zone_a
        events = tracker.update((999, 999), 2.0)  # move to empty

        assert len(events) == 1
        assert events[0].type is SpatialEventType.ZONE_EXIT
        assert events[0].zone_id == "zone_a"

    def test_cursor_moves_empty_to_zone_emits_enter_only(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Moving from empty space into a zone emits only ENTER."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((999, 999), 0.5)  # start in empty space
        events = tracker.update((50, 25), 1.0)  # enter zone_a

        assert len(events) == 1
        assert events[0].type is SpatialEventType.ZONE_ENTER
        assert events[0].zone_id == "zone_a"

    def test_cursor_stays_in_same_zone_no_enter_exit_events(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Staying in the same zone emits no enter/exit events."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)  # enter
        events = tracker.update((55, 28), 1.1)  # still inside zone_a

        # No enter/exit events; possibly no events at all (hover not reached)
        enter_exit = [
            e for e in events
            if e.type in (SpatialEventType.ZONE_ENTER, SpatialEventType.ZONE_EXIT)
        ]
        assert len(enter_exit) == 0

    def test_cursor_stays_outside_all_zones_no_events(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Cursor remaining outside all zones emits nothing."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        events1 = tracker.update((999, 999), 1.0)
        events2 = tracker.update((998, 998), 2.0)

        assert events1 == []
        assert events2 == []

    def test_first_update_in_zone_emits_enter_no_previous_exit(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Very first update landing in a zone: ENTER only, no EXIT."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        events = tracker.update((50, 25), 1.0)

        assert len(events) == 1
        assert events[0].type is SpatialEventType.ZONE_ENTER
        # Confirm no exit in the batch
        exits = [e for e in events if e.type is SpatialEventType.ZONE_EXIT]
        assert len(exits) == 0

    def test_overlapping_zones_enters_smallest(
        self,
        registry: ZoneRegistry,
        settings: Settings,
    ) -> None:
        """With overlapping zones, the smallest zone is entered."""
        big = _make_zone("big", 0, 0, 500, 500)
        small = _make_zone("small", 20, 20, 30, 30)
        registry.register(big)
        registry.register(small)
        tracker = ZoneTracker(registry, settings)

        events = tracker.update((35, 35), 1.0)

        assert len(events) == 1
        assert events[0].type is SpatialEventType.ZONE_ENTER
        assert events[0].zone_id == "small"

    def test_exit_event_position_matches_cursor(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """EXIT event position is the cursor position at exit time."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)
        events = tracker.update((999, 999), 2.0)

        assert events[0].position == (999, 999)

    def test_enter_event_position_matches_cursor(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """ENTER event position is the cursor position at enter time."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        events = tracker.update((55, 30), 1.0)

        assert events[0].position == (55, 30)

    def test_enter_event_data_is_empty_dict(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """ENTER event data is an empty dict."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        events = tracker.update((50, 25), 1.0)

        assert events[0].data == {}

    def test_exit_event_timestamp_matches_frame(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """EXIT event timestamp is the timestamp of the exit frame."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)
        events = tracker.update((999, 999), 5.5)

        assert events[0].timestamp == 5.5

    def test_rapid_zone_transitions(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
        zone_b: Zone,
    ) -> None:
        """Multiple rapid transitions produce correct event sequence."""
        registry.register(zone_a)
        registry.register(zone_b)
        tracker = ZoneTracker(registry, settings)

        # enter A
        e1 = tracker.update((50, 25), 1.0)
        # exit A, enter B
        e2 = tracker.update((240, 215), 2.0)
        # exit B, enter A
        e3 = tracker.update((50, 25), 3.0)

        assert len(e1) == 1
        assert e1[0].type is SpatialEventType.ZONE_ENTER
        assert e1[0].zone_id == "zone_a"

        assert len(e2) == 2
        assert e2[0].type is SpatialEventType.ZONE_EXIT
        assert e2[0].zone_id == "zone_a"
        assert e2[1].type is SpatialEventType.ZONE_ENTER
        assert e2[1].zone_id == "zone_b"

        assert len(e3) == 2
        assert e3[0].type is SpatialEventType.ZONE_EXIT
        assert e3[0].zone_id == "zone_b"
        assert e3[1].type is SpatialEventType.ZONE_ENTER
        assert e3[1].zone_id == "zone_a"

    def test_exit_duration_zero_when_instant(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """EXIT duration is 0.0 when enter and exit are at the same time."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 5.0)
        events = tracker.update((999, 999), 5.0)

        assert events[0].data["duration"] == pytest.approx(0.0)


# ==================================================================
# Hover Detection
# ==================================================================


class TestHoverDetection:
    """Tests for hover threshold detection and event emission."""

    def test_hover_not_emitted_before_threshold(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """No ZONE_HOVER emitted before hover_threshold_ms is reached."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)  # enter
        # 200ms later (threshold is 300ms)
        events = tracker.update((50, 25), 1.2)

        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 0

    def test_hover_emitted_at_threshold(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """ZONE_HOVER is emitted once the threshold is exactly reached."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)  # enter
        # Exactly 300ms = 0.3s later
        events = tracker.update((50, 25), 1.3)

        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 1
        assert hover_events[0].zone_id == "zone_a"

    def test_hover_emitted_after_threshold(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """ZONE_HOVER is emitted when threshold is exceeded."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)  # enter
        events = tracker.update((55, 28), 1.5)  # 500ms > 300ms threshold

        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 1
        assert hover_events[0].zone_id == "zone_a"

    def test_hover_not_re_emitted_on_subsequent_frames(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """After hover fires once, subsequent frames do not re-emit it."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)  # enter
        tracker.update((50, 25), 1.5)  # hover emitted
        events = tracker.update((55, 28), 2.0)  # still in zone

        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 0

    def test_hover_resets_when_entering_new_zone(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
        zone_b: Zone,
    ) -> None:
        """Moving to a new zone resets the hover timer."""
        registry.register(zone_a)
        registry.register(zone_b)
        tracker = ZoneTracker(registry, settings)

        # Enter zone_a and trigger hover
        tracker.update((50, 25), 1.0)
        tracker.update((50, 25), 1.5)  # hover in A

        # Move to zone_b at t=2.0
        tracker.update((240, 215), 2.0)

        # 200ms in B: not yet at threshold
        events = tracker.update((240, 215), 2.2)
        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 0

        # Well past 300ms in B (use 0.5 to avoid float precision)
        events = tracker.update((240, 215), 2.5)
        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 1
        assert hover_events[0].zone_id == "zone_b"

    def test_hover_resets_when_leaving_all_zones(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Leaving all zones clears hover state; re-entering starts fresh."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        # Enter and hover in zone_a
        tracker.update((50, 25), 1.0)
        tracker.update((50, 25), 1.5)  # hover emitted

        # Leave zone
        tracker.update((999, 999), 2.0)

        # Re-enter zone_a at t=3.0
        tracker.update((50, 25), 3.0)

        # 200ms: not yet
        events = tracker.update((50, 25), 3.2)
        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 0

        # Well past 300ms (use 0.5 to avoid float precision)
        events = tracker.update((50, 25), 3.5)
        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 1

    def test_hover_duration_data_is_correct(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """ZONE_HOVER event data['duration'] matches actual dwell time."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 10.0)  # enter
        events = tracker.update((50, 25), 10.5)  # 500ms later

        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 1
        assert hover_events[0].data["duration"] == pytest.approx(0.5)

    def test_custom_hover_threshold_ms(
        self,
        registry: ZoneRegistry,
        custom_settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Custom hover_threshold_ms=100 fires hover earlier."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, custom_settings)

        tracker.update((50, 25), 1.0)  # enter

        # 90ms: not yet
        events = tracker.update((50, 25), 1.09)
        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 0

        # 100ms: should fire
        events = tracker.update((50, 25), 1.1)
        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert len(hover_events) == 1

    def test_hover_event_position_matches_cursor(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """ZONE_HOVER event position matches the cursor at emission."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)
        events = tracker.update((55, 28), 1.5)

        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert hover_events[0].position == (55, 28)

    def test_hover_event_timestamp_matches_frame(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """ZONE_HOVER event timestamp matches the frame timestamp."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)
        events = tracker.update((50, 25), 1.5)

        hover_events = [
            e for e in events if e.type is SpatialEventType.ZONE_HOVER
        ]
        assert hover_events[0].timestamp == 1.5


# ==================================================================
# Query Methods
# ==================================================================


class TestQueryMethods:
    """Tests for get_current_zone, get_current_zone_object, is_in_zone,
    get_hover_duration, and get_event_history."""

    def test_get_current_zone_returns_correct_id(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """get_current_zone returns the ID of the zone the cursor is in."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)

        assert tracker.get_current_zone() == "zone_a"

    def test_get_current_zone_returns_none_outside(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """get_current_zone returns None when cursor is not in any zone."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((999, 999), 1.0)

        assert tracker.get_current_zone() is None

    def test_get_current_zone_none_initially(
        self,
        tracker: ZoneTracker,
    ) -> None:
        """get_current_zone returns None before any updates."""
        assert tracker.get_current_zone() is None

    def test_get_current_zone_object_returns_zone(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """get_current_zone_object returns the Zone from the registry."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)
        zone_obj = tracker.get_current_zone_object()

        assert zone_obj is not None
        assert zone_obj.id == "zone_a"
        assert zone_obj is zone_a

    def test_get_current_zone_object_returns_none_when_removed(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """get_current_zone_object returns None if zone removed from registry."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)
        registry.remove("zone_a")

        assert tracker.get_current_zone_object() is None

    def test_get_current_zone_object_none_outside(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """get_current_zone_object returns None when outside zones."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((999, 999), 1.0)

        assert tracker.get_current_zone_object() is None

    def test_is_in_zone_true_for_current(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """is_in_zone returns True for the zone the cursor occupies."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)

        assert tracker.is_in_zone("zone_a") is True

    def test_is_in_zone_false_for_other(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
        zone_b: Zone,
    ) -> None:
        """is_in_zone returns False for a zone the cursor is not in."""
        registry.register(zone_a)
        registry.register(zone_b)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)  # in zone_a

        assert tracker.is_in_zone("zone_b") is False

    def test_is_in_zone_false_when_outside(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """is_in_zone returns False when cursor is outside all zones."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((999, 999), 1.0)

        assert tracker.is_in_zone("zone_a") is False

    def test_get_hover_duration_returns_duration(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """get_hover_duration returns elapsed time while in a zone."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 10.0)  # enter

        duration = tracker.get_hover_duration(10.5)
        assert duration is not None
        assert duration == pytest.approx(0.5)

    def test_get_hover_duration_returns_none_outside(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """get_hover_duration returns None when not in any zone."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((999, 999), 10.0)

        assert tracker.get_hover_duration(10.5) is None

    def test_get_hover_duration_returns_none_initially(
        self,
        tracker: ZoneTracker,
    ) -> None:
        """get_hover_duration returns None before any updates."""
        assert tracker.get_hover_duration(1.0) is None

    def test_get_event_history_chronological_order(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
        zone_b: Zone,
    ) -> None:
        """get_event_history returns events in chronological order."""
        registry.register(zone_a)
        registry.register(zone_b)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)   # ENTER zone_a
        tracker.update((240, 215), 2.0)  # EXIT zone_a, ENTER zone_b
        tracker.update((999, 999), 3.0)  # EXIT zone_b

        history = tracker.get_event_history(limit=100)
        assert len(history) == 4
        # Timestamps should be non-decreasing
        for i in range(len(history) - 1):
            assert history[i].timestamp <= history[i + 1].timestamp

    def test_get_event_history_respects_limit(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """get_event_history returns at most `limit` events."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        # Generate several events: in, out, in, out...
        for i in range(10):
            tracker.update((50, 25), float(i * 2))      # enter
            tracker.update((999, 999), float(i * 2 + 1))  # exit

        history = tracker.get_event_history(limit=5)
        assert len(history) == 5
        # Should be the 5 most recent events
        all_history = tracker.get_event_history(limit=100)
        assert history == all_history[-5:]

    def test_get_event_history_default_limit(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """get_event_history defaults to 50 events."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        # Generate 60 enter events + 60 exit events = 120 events
        for i in range(60):
            tracker.update((50, 25), float(i * 2))
            tracker.update((999, 999), float(i * 2 + 1))

        history = tracker.get_event_history()
        assert len(history) == 50


# ==================================================================
# Reset and Edge Cases
# ==================================================================


class TestReset:
    """Tests for the reset() method."""

    def test_reset_clears_current_zone(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """reset() clears the current zone to None."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)
        assert tracker.get_current_zone() == "zone_a"

        tracker.reset()
        assert tracker.get_current_zone() is None

    def test_reset_clears_event_history(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """reset() empties the event history."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)
        assert len(tracker.get_event_history(limit=100)) > 0

        tracker.reset()
        assert tracker.get_event_history(limit=100) == []

    def test_reset_clears_hover_state(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """reset() clears hover state so re-entering starts fresh."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        # Enter and trigger hover
        tracker.update((50, 25), 1.0)
        tracker.update((50, 25), 1.5)  # hover emitted

        tracker.reset()

        # Hover duration should be None
        assert tracker.get_hover_duration(2.0) is None

        # Re-entering should produce fresh ENTER event
        events = tracker.update((50, 25), 2.0)
        assert len(events) == 1
        assert events[0].type is SpatialEventType.ZONE_ENTER


class TestEdgeCases:
    """Miscellaneous edge-case tests."""

    def test_empty_registry_no_events(
        self,
        registry: ZoneRegistry,
        settings: Settings,
    ) -> None:
        """Update with an empty registry produces no events."""
        tracker = ZoneTracker(registry, settings)

        events = tracker.update((50, 25), 1.0)

        assert events == []

    def test_zone_removed_while_cursor_inside_emits_exit(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Zone removed from registry while cursor inside emits EXIT."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        tracker.update((50, 25), 1.0)  # enter zone_a
        assert tracker.get_current_zone() == "zone_a"

        # Remove zone from registry
        registry.remove("zone_a")

        # Next update: cursor at same position but zone is gone
        events = tracker.update((50, 25), 2.0)

        assert len(events) == 1
        assert events[0].type is SpatialEventType.ZONE_EXIT
        assert events[0].zone_id == "zone_a"
        assert events[0].data["duration"] == pytest.approx(1.0)

    def test_history_maxlen_respected(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Adding more than history_maxlen events drops oldest events."""
        tracker = ZoneTracker(registry, settings, history_maxlen=10)
        registry.register(zone_a)

        # Generate 20 enter/exit pairs = 40 events
        for i in range(20):
            tracker.update((50, 25), float(i * 2))
            tracker.update((999, 999), float(i * 2 + 1))

        # Only the most recent 10 should be retained
        history = tracker.get_event_history(limit=100)
        assert len(history) == 10

    def test_negative_limit_returns_empty_list(
        self,
        tracker: ZoneTracker,
    ) -> None:
        """Negative limit to get_event_history returns an empty list."""
        assert tracker.get_event_history(limit=-1) == []

    def test_zero_limit_returns_empty_list(
        self,
        tracker: ZoneTracker,
    ) -> None:
        """Zero limit to get_event_history returns an empty list."""
        assert tracker.get_event_history(limit=0) == []

    def test_repr_format(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """__repr__ includes current zone, hovering state, and history count."""
        tracker = ZoneTracker(registry, settings)

        # Initial state
        r = repr(tracker)
        assert "current_zone='none'" in r
        assert "history=0" in r

        # After entering a zone
        registry.register(zone_a)
        tracker.update((50, 25), 1.0)
        r = repr(tracker)
        assert "current_zone='zone_a'" in r
        assert "history=1" in r

    def test_properties_expose_registry_and_settings(
        self,
        registry: ZoneRegistry,
        settings: Settings,
    ) -> None:
        """Public properties return the injected registry and settings."""
        tracker = ZoneTracker(registry, settings)

        assert tracker.registry is registry
        assert tracker.settings is settings

    def test_zone_added_to_registry_after_construction(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """Tracker picks up zones added to the registry after construction."""
        tracker = ZoneTracker(registry, settings)

        events1 = tracker.update((50, 25), 1.0)
        assert events1 == []  # zone not yet registered

        registry.register(zone_a)
        events2 = tracker.update((50, 25), 2.0)
        assert len(events2) == 1
        assert events2[0].type is SpatialEventType.ZONE_ENTER

    def test_history_maxlen_default_is_1000(
        self,
        registry: ZoneRegistry,
        settings: Settings,
    ) -> None:
        """Default history_maxlen is 1000."""
        tracker = ZoneTracker(registry, settings)
        # Access internal deque maxlen
        assert tracker._history.maxlen == 1000

    def test_reset_then_update_behaves_like_fresh_tracker(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """After reset(), update() behaves as if the tracker is new."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        # Build some state
        tracker.update((50, 25), 1.0)
        tracker.update((50, 25), 1.5)  # hover
        tracker.update((999, 999), 2.0)  # exit
        tracker.reset()

        # Now re-enter: should get fresh ENTER, no EXIT
        events = tracker.update((50, 25), 3.0)
        assert len(events) == 1
        assert events[0].type is SpatialEventType.ZONE_ENTER
        assert events[0].zone_id == "zone_a"

    def test_events_stored_in_history(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        zone_a: Zone,
    ) -> None:
        """All events returned from update() are also in the history."""
        registry.register(zone_a)
        tracker = ZoneTracker(registry, settings)

        returned_events: list[SpatialEvent] = []
        returned_events.extend(tracker.update((50, 25), 1.0))
        returned_events.extend(tracker.update((999, 999), 2.0))

        history = tracker.get_event_history(limit=100)
        assert history == returned_events

    def test_hover_not_emitted_on_enter_frame(
        self,
        registry: ZoneRegistry,
        zone_a: Zone,
    ) -> None:
        """On the frame that triggers ENTER, no hover is emitted."""
        # Use 0ms threshold to test that hover can't fire on enter frame
        instant_settings = Settings(hover_threshold_ms=0)
        registry.register(zone_a)
        tracker = ZoneTracker(registry, instant_settings)

        events = tracker.update((50, 25), 1.0)

        # Only ENTER should fire; hover check only runs on subsequent frames
        assert len(events) == 1
        assert events[0].type is SpatialEventType.ZONE_ENTER
