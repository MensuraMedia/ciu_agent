"""Tests for CIU Agent data models: zones, events, and actions.

Covers all enumerations, dataclass construction, validation logic,
and geometric methods defined in the models package.
"""

from __future__ import annotations

import pytest

from ciu_agent.models.actions import (
    Action,
    ActionStatus,
    ActionType,
    Trajectory,
    TrajectoryType,
)
from ciu_agent.models.events import SpatialEvent, SpatialEventType
from ciu_agent.models.zone import Rectangle, Zone, ZoneState, ZoneType

# ---------------------------------------------------------------------------
# ZoneType enum
# ---------------------------------------------------------------------------


class TestZoneType:
    """Tests for the ZoneType enumeration."""

    EXPECTED_MEMBERS = [
        "BUTTON",
        "TEXT_FIELD",
        "LINK",
        "DROPDOWN",
        "CHECKBOX",
        "SLIDER",
        "MENU_ITEM",
        "TAB",
        "SCROLL_AREA",
        "STATIC",
        "UNKNOWN",
    ]

    @pytest.mark.parametrize("member", EXPECTED_MEMBERS)
    def test_member_exists(self, member: str) -> None:
        """Each expected member must be accessible on the enum."""
        assert hasattr(ZoneType, member)

    def test_total_member_count(self) -> None:
        """ZoneType must contain exactly 11 members."""
        assert len(ZoneType) == 11

    def test_values_are_lowercase_strings(self) -> None:
        """Every ZoneType value must be a lowercase snake_case string."""
        for member in ZoneType:
            assert isinstance(member.value, str)
            assert member.value == member.value.lower()


# ---------------------------------------------------------------------------
# ZoneState enum
# ---------------------------------------------------------------------------


class TestZoneState:
    """Tests for the ZoneState enumeration."""

    EXPECTED_MEMBERS = [
        "ENABLED",
        "DISABLED",
        "FOCUSED",
        "HOVERED",
        "PRESSED",
        "CHECKED",
        "UNCHECKED",
        "EXPANDED",
        "COLLAPSED",
        "UNKNOWN",
    ]

    @pytest.mark.parametrize("member", EXPECTED_MEMBERS)
    def test_member_exists(self, member: str) -> None:
        """Each expected member must be accessible on the enum."""
        assert hasattr(ZoneState, member)

    def test_total_member_count(self) -> None:
        """ZoneState must contain exactly 10 members."""
        assert len(ZoneState) == 10

    def test_values_are_lowercase_strings(self) -> None:
        """Every ZoneState value must be a lowercase snake_case string."""
        for member in ZoneState:
            assert isinstance(member.value, str)
            assert member.value == member.value.lower()


# ---------------------------------------------------------------------------
# Rectangle
# ---------------------------------------------------------------------------


class TestRectangle:
    """Tests for the Rectangle dataclass and its geometric helpers."""

    def test_construction_basic(self) -> None:
        """Rectangle stores the four positional attributes correctly."""
        r = Rectangle(x=10, y=20, width=100, height=50)
        assert r.x == 10
        assert r.y == 20
        assert r.width == 100
        assert r.height == 50

    def test_construction_zero_dimensions(self) -> None:
        """A zero-area rectangle is valid (used for collapsed zones)."""
        r = Rectangle(x=5, y=5, width=0, height=0)
        assert r.area() == 0

    # -- validation --------------------------------------------------------

    def test_negative_width_raises(self) -> None:
        """Negative width must be rejected at construction time."""
        with pytest.raises(ValueError, match="width must be >= 0"):
            Rectangle(x=0, y=0, width=-1, height=10)

    def test_negative_height_raises(self) -> None:
        """Negative height must be rejected at construction time."""
        with pytest.raises(ValueError, match="height must be >= 0"):
            Rectangle(x=0, y=0, width=10, height=-5)

    # -- contains_point ----------------------------------------------------

    def test_contains_point_inside(self) -> None:
        """A point clearly inside the rectangle returns True."""
        r = Rectangle(x=10, y=10, width=100, height=50)
        assert r.contains_point(50, 30) is True

    def test_contains_point_outside(self) -> None:
        """A point outside all edges returns False."""
        r = Rectangle(x=10, y=10, width=100, height=50)
        assert r.contains_point(200, 200) is False

    def test_contains_point_left_of(self) -> None:
        """A point to the left of the rectangle returns False."""
        r = Rectangle(x=10, y=10, width=100, height=50)
        assert r.contains_point(5, 30) is False

    def test_contains_point_above(self) -> None:
        """A point above the rectangle returns False."""
        r = Rectangle(x=10, y=10, width=100, height=50)
        assert r.contains_point(50, 5) is False

    def test_contains_point_on_top_left_edge(self) -> None:
        """The top-left corner is inside the rectangle (inclusive)."""
        r = Rectangle(x=10, y=10, width=100, height=50)
        assert r.contains_point(10, 10) is True

    def test_contains_point_on_bottom_right_edge(self) -> None:
        """The bottom-right corner is inside the rectangle (inclusive)."""
        r = Rectangle(x=10, y=10, width=100, height=50)
        assert r.contains_point(110, 60) is True

    def test_contains_point_on_right_edge(self) -> None:
        """A point on the right edge (x + width) is inside."""
        r = Rectangle(x=0, y=0, width=50, height=50)
        assert r.contains_point(50, 25) is True

    def test_contains_point_on_bottom_edge(self) -> None:
        """A point on the bottom edge (y + height) is inside."""
        r = Rectangle(x=0, y=0, width=50, height=50)
        assert r.contains_point(25, 50) is True

    def test_contains_point_just_outside_right(self) -> None:
        """One pixel past the right edge is outside."""
        r = Rectangle(x=0, y=0, width=50, height=50)
        assert r.contains_point(51, 25) is False

    def test_contains_point_just_outside_bottom(self) -> None:
        """One pixel past the bottom edge is outside."""
        r = Rectangle(x=0, y=0, width=50, height=50)
        assert r.contains_point(25, 51) is False

    # -- center ------------------------------------------------------------

    def test_center_even_dimensions(self) -> None:
        """Center of an even-sized rectangle is exact."""
        r = Rectangle(x=0, y=0, width=100, height=50)
        assert r.center() == (50, 25)

    def test_center_odd_dimensions(self) -> None:
        """Center uses integer division so it truncates toward zero."""
        r = Rectangle(x=0, y=0, width=101, height=51)
        assert r.center() == (50, 25)

    def test_center_with_offset(self) -> None:
        """Center accounts for the rectangle's position offset."""
        r = Rectangle(x=20, y=30, width=100, height=50)
        assert r.center() == (70, 55)

    def test_center_zero_area(self) -> None:
        """A zero-area rectangle's center is its position."""
        r = Rectangle(x=42, y=99, width=0, height=0)
        assert r.center() == (42, 99)

    # -- overlaps ----------------------------------------------------------

    def test_overlaps_yes(self) -> None:
        """Two partially overlapping rectangles return True."""
        a = Rectangle(x=0, y=0, width=100, height=100)
        b = Rectangle(x=50, y=50, width=100, height=100)
        assert a.overlaps(b) is True
        assert b.overlaps(a) is True

    def test_overlaps_no_separated(self) -> None:
        """Two clearly separated rectangles return False."""
        a = Rectangle(x=0, y=0, width=10, height=10)
        b = Rectangle(x=100, y=100, width=10, height=10)
        assert a.overlaps(b) is False
        assert b.overlaps(a) is False

    def test_overlaps_touching_edges_not_overlapping(self) -> None:
        """Touching edges alone do not count as overlap."""
        a = Rectangle(x=0, y=0, width=50, height=50)
        b = Rectangle(x=50, y=0, width=50, height=50)
        assert a.overlaps(b) is False
        assert b.overlaps(a) is False

    def test_overlaps_contained(self) -> None:
        """A smaller rectangle fully inside a larger one overlaps."""
        outer = Rectangle(x=0, y=0, width=200, height=200)
        inner = Rectangle(x=50, y=50, width=20, height=20)
        assert outer.overlaps(inner) is True
        assert inner.overlaps(outer) is True

    def test_overlaps_zero_area_returns_false(self) -> None:
        """A zero-area rectangle never overlaps anything."""
        a = Rectangle(x=10, y=10, width=0, height=0)
        b = Rectangle(x=0, y=0, width=100, height=100)
        assert a.overlaps(b) is False
        assert b.overlaps(a) is False

    def test_overlaps_same_rectangle(self) -> None:
        """A rectangle overlaps with itself (non-zero area)."""
        r = Rectangle(x=10, y=10, width=50, height=50)
        assert r.overlaps(r) is True

    # -- area --------------------------------------------------------------

    def test_area_normal(self) -> None:
        """Area is width * height."""
        r = Rectangle(x=0, y=0, width=100, height=50)
        assert r.area() == 5000

    def test_area_zero(self) -> None:
        """Zero width or height gives zero area."""
        assert Rectangle(x=0, y=0, width=0, height=100).area() == 0
        assert Rectangle(x=0, y=0, width=100, height=0).area() == 0

    def test_area_one_pixel(self) -> None:
        """A 1x1 rectangle has area 1."""
        r = Rectangle(x=0, y=0, width=1, height=1)
        assert r.area() == 1


# ---------------------------------------------------------------------------
# Zone
# ---------------------------------------------------------------------------


class TestZone:
    """Tests for the Zone dataclass."""

    def _make_zone(self, **overrides: object) -> Zone:
        """Create a Zone with sensible defaults, applying overrides."""
        defaults: dict[str, object] = {
            "id": "zone_1",
            "bounds": Rectangle(x=0, y=0, width=100, height=50),
            "type": ZoneType.BUTTON,
            "label": "OK",
        }
        defaults.update(overrides)
        return Zone(**defaults)  # type: ignore[arg-type]

    def test_construction_with_defaults(self) -> None:
        """Zone fills optional fields with documented defaults."""
        z = self._make_zone()
        assert z.id == "zone_1"
        assert z.state == ZoneState.ENABLED
        assert z.parent_id is None
        assert z.confidence == 1.0
        assert z.last_seen == 0.0

    def test_construction_explicit_fields(self) -> None:
        """Explicitly set optional fields are preserved."""
        z = self._make_zone(
            state=ZoneState.FOCUSED,
            parent_id="parent_1",
            confidence=0.85,
            last_seen=1234567890.0,
        )
        assert z.state == ZoneState.FOCUSED
        assert z.parent_id == "parent_1"
        assert z.confidence == 0.85
        assert z.last_seen == 1234567890.0

    def test_contains_point_delegates_to_bounds(self) -> None:
        """Zone.contains_point forwards to Rectangle.contains_point."""
        z = self._make_zone(bounds=Rectangle(x=10, y=10, width=80, height=40))
        assert z.contains_point(50, 30) is True
        assert z.contains_point(5, 5) is False

    # -- confidence validation ---------------------------------------------

    def test_confidence_valid_zero(self) -> None:
        """Confidence of 0.0 is acceptable (lowest bound)."""
        z = self._make_zone(confidence=0.0)
        assert z.confidence == 0.0

    def test_confidence_valid_one(self) -> None:
        """Confidence of 1.0 is acceptable (upper bound)."""
        z = self._make_zone(confidence=1.0)
        assert z.confidence == 1.0

    def test_confidence_valid_middle(self) -> None:
        """A mid-range confidence value is accepted."""
        z = self._make_zone(confidence=0.5)
        assert z.confidence == 0.5

    def test_confidence_too_high_raises(self) -> None:
        """Confidence above 1.0 must be rejected."""
        with pytest.raises(ValueError, match="confidence"):
            self._make_zone(confidence=1.01)

    def test_confidence_negative_raises(self) -> None:
        """Negative confidence must be rejected."""
        with pytest.raises(ValueError, match="confidence"):
            self._make_zone(confidence=-0.1)


# ---------------------------------------------------------------------------
# SpatialEventType
# ---------------------------------------------------------------------------


class TestSpatialEventType:
    """Tests for the SpatialEventType enumeration."""

    EXPECTED_MEMBERS = [
        "ZONE_ENTER",
        "ZONE_EXIT",
        "ZONE_HOVER",
        "ZONE_CLICK",
        "ZONE_TYPE",
        "BRUSH_LOST",
    ]

    @pytest.mark.parametrize("member", EXPECTED_MEMBERS)
    def test_member_exists(self, member: str) -> None:
        """Each expected member must be accessible on the enum."""
        assert hasattr(SpatialEventType, member)

    def test_total_member_count(self) -> None:
        """SpatialEventType must contain exactly 6 members."""
        assert len(SpatialEventType) == 6


# ---------------------------------------------------------------------------
# SpatialEvent
# ---------------------------------------------------------------------------


class TestSpatialEvent:
    """Tests for the SpatialEvent dataclass."""

    def test_construction_with_defaults(self) -> None:
        """SpatialEvent fills data with an empty dict by default."""
        ev = SpatialEvent(
            type=SpatialEventType.ZONE_CLICK,
            zone_id="btn_ok",
            timestamp=100.0,
            position=(50, 25),
        )
        assert ev.type == SpatialEventType.ZONE_CLICK
        assert ev.zone_id == "btn_ok"
        assert ev.timestamp == 100.0
        assert ev.position == (50, 25)
        assert ev.data == {}

    def test_construction_with_data(self) -> None:
        """The data dict carries event-specific payload."""
        payload = {"button": "left", "modifier": "ctrl"}
        ev = SpatialEvent(
            type=SpatialEventType.ZONE_CLICK,
            zone_id="btn_ok",
            timestamp=200.0,
            position=(60, 30),
            data=payload,
        )
        assert ev.data == {"button": "left", "modifier": "ctrl"}

    def test_data_dict_is_mutable(self) -> None:
        """The data dict can be modified after construction."""
        ev = SpatialEvent(
            type=SpatialEventType.ZONE_HOVER,
            zone_id="panel_1",
            timestamp=300.0,
            position=(70, 35),
        )
        ev.data["duration"] = 1.5
        assert ev.data["duration"] == 1.5

    def test_brush_lost_event(self) -> None:
        """BRUSH_LOST events use an empty zone_id by convention."""
        ev = SpatialEvent(
            type=SpatialEventType.BRUSH_LOST,
            zone_id="",
            timestamp=400.0,
            position=(0, 0),
            data={"expected_zone": "btn_cancel"},
        )
        assert ev.zone_id == ""
        assert ev.data["expected_zone"] == "btn_cancel"

    def test_default_data_dicts_are_independent(self) -> None:
        """Each SpatialEvent gets its own default data dict."""
        ev1 = SpatialEvent(
            type=SpatialEventType.ZONE_ENTER,
            zone_id="z1",
            timestamp=0.0,
            position=(0, 0),
        )
        ev2 = SpatialEvent(
            type=SpatialEventType.ZONE_EXIT,
            zone_id="z2",
            timestamp=1.0,
            position=(1, 1),
        )
        ev1.data["key"] = "value"
        assert "key" not in ev2.data


# ---------------------------------------------------------------------------
# ActionType
# ---------------------------------------------------------------------------


class TestActionType:
    """Tests for the ActionType enumeration."""

    EXPECTED_MEMBERS = [
        "CLICK",
        "DOUBLE_CLICK",
        "TYPE_TEXT",
        "KEY_PRESS",
        "SCROLL",
        "DRAG",
        "MOVE",
    ]

    @pytest.mark.parametrize("member", EXPECTED_MEMBERS)
    def test_member_exists(self, member: str) -> None:
        """Each expected member must be accessible on the enum."""
        assert hasattr(ActionType, member)

    def test_total_member_count(self) -> None:
        """ActionType must contain exactly 7 members."""
        assert len(ActionType) == 7


# ---------------------------------------------------------------------------
# ActionStatus
# ---------------------------------------------------------------------------


class TestActionStatus:
    """Tests for the ActionStatus enumeration."""

    EXPECTED_MEMBERS = [
        "PENDING",
        "IN_PROGRESS",
        "COMPLETED",
        "FAILED",
    ]

    @pytest.mark.parametrize("member", EXPECTED_MEMBERS)
    def test_member_exists(self, member: str) -> None:
        """Each expected member must be accessible on the enum."""
        assert hasattr(ActionStatus, member)

    def test_total_member_count(self) -> None:
        """ActionStatus must contain exactly 4 members."""
        assert len(ActionStatus) == 4


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------


class TestAction:
    """Tests for the Action dataclass."""

    def test_construction_with_defaults(self) -> None:
        """Action fills status, parameters, timestamp, result defaults."""
        a = Action(type=ActionType.CLICK, target_zone_id="btn_save")
        assert a.type == ActionType.CLICK
        assert a.target_zone_id == "btn_save"
        assert a.status == ActionStatus.PENDING
        assert a.parameters == {}
        assert a.timestamp == 0.0
        assert a.result == ""

    def test_construction_explicit_fields(self) -> None:
        """All optional fields can be set explicitly."""
        a = Action(
            type=ActionType.TYPE_TEXT,
            target_zone_id="input_name",
            status=ActionStatus.COMPLETED,
            parameters={"text": "hello world"},
            timestamp=999.0,
            result="typed 11 characters",
        )
        assert a.status == ActionStatus.COMPLETED
        assert a.parameters == {"text": "hello world"}
        assert a.timestamp == 999.0
        assert a.result == "typed 11 characters"

    def test_default_parameters_dicts_are_independent(self) -> None:
        """Each Action gets its own default parameters dict."""
        a1 = Action(type=ActionType.MOVE, target_zone_id="z1")
        a2 = Action(type=ActionType.MOVE, target_zone_id="z2")
        a1.parameters["extra"] = True
        assert "extra" not in a2.parameters


# ---------------------------------------------------------------------------
# TrajectoryType
# ---------------------------------------------------------------------------


class TestTrajectoryType:
    """Tests for the TrajectoryType enumeration."""

    EXPECTED_MEMBERS = [
        "DIRECT",
        "SAFE",
        "EXPLORATORY",
    ]

    @pytest.mark.parametrize("member", EXPECTED_MEMBERS)
    def test_member_exists(self, member: str) -> None:
        """Each expected member must be accessible on the enum."""
        assert hasattr(TrajectoryType, member)

    def test_total_member_count(self) -> None:
        """TrajectoryType must contain exactly 3 members."""
        assert len(TrajectoryType) == 3


# ---------------------------------------------------------------------------
# Trajectory
# ---------------------------------------------------------------------------


class TestTrajectory:
    """Tests for the Trajectory dataclass."""

    def test_construction_with_points(self) -> None:
        """Trajectory stores the waypoints list and target zone."""
        waypoints = [(0, 0), (50, 25), (100, 50)]
        t = Trajectory(
            type=TrajectoryType.DIRECT,
            points=waypoints,
            target_zone_id="btn_ok",
        )
        assert t.type == TrajectoryType.DIRECT
        assert t.points == [(0, 0), (50, 25), (100, 50)]
        assert t.target_zone_id == "btn_ok"
        assert t.avoid_zone_ids == []

    def test_construction_with_avoid_zones(self) -> None:
        """SAFE trajectories carry an avoid_zone_ids list."""
        t = Trajectory(
            type=TrajectoryType.SAFE,
            points=[(0, 0), (10, 10)],
            target_zone_id="target_1",
            avoid_zone_ids=["danger_1", "danger_2"],
        )
        assert t.avoid_zone_ids == ["danger_1", "danger_2"]

    def test_empty_points_list(self) -> None:
        """A trajectory with no waypoints is structurally valid."""
        t = Trajectory(
            type=TrajectoryType.EXPLORATORY,
            points=[],
            target_zone_id="unknown_1",
        )
        assert t.points == []

    def test_default_avoid_zone_ids_are_independent(self) -> None:
        """Each Trajectory gets its own default avoid_zone_ids list."""
        t1 = Trajectory(
            type=TrajectoryType.DIRECT,
            points=[(0, 0)],
            target_zone_id="a",
        )
        t2 = Trajectory(
            type=TrajectoryType.DIRECT,
            points=[(1, 1)],
            target_zone_id="b",
        )
        t1.avoid_zone_ids.append("z99")
        assert "z99" not in t2.avoid_zone_ids
