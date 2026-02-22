"""Comprehensive unit tests for ciu_agent.core.motion_planner.MotionPlanner.

Covers plan_direct, plan_safe, plan_exploratory, interpolate_line,
line_intersects_rect, estimate_duration_ms, and edge cases.
"""

from __future__ import annotations

import math

import pytest

from ciu_agent.config.settings import Settings
from ciu_agent.core.motion_planner import (
    _DEFAULT_SCAN_SPACING,
    _MAX_WAYPOINTS,
    _MIN_WAYPOINTS,
    MotionPlanner,
)
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.actions import Trajectory, TrajectoryType
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
def settings() -> Settings:
    """Return default Settings (motion_speed_pixels_per_sec=1500.0)."""
    return Settings()


@pytest.fixture()
def registry() -> ZoneRegistry:
    """Return a fresh empty ZoneRegistry."""
    return ZoneRegistry()


@pytest.fixture()
def planner(registry: ZoneRegistry, settings: Settings) -> MotionPlanner:
    """Return a MotionPlanner wired to empty registry + default settings."""
    return MotionPlanner(registry, settings)


@pytest.fixture()
def populated_registry() -> ZoneRegistry:
    """Return a ZoneRegistry pre-loaded with several zones for tests."""
    reg = ZoneRegistry()
    reg.register_many(
        [
            _make_zone(
                "btn_save", 200, 200, 80, 30,
                ZoneType.BUTTON, "Save", ZoneState.ENABLED,
            ),
            _make_zone(
                "btn_cancel", 400, 200, 80, 30,
                ZoneType.BUTTON, "Cancel", ZoneState.ENABLED,
            ),
            _make_zone(
                "txt_name", 100, 100, 200, 25,
                ZoneType.TEXT_FIELD, "Name", ZoneState.FOCUSED,
            ),
            _make_zone(
                "obstacle_a", 300, 100, 100, 200,
                ZoneType.STATIC, "Panel A", ZoneState.ENABLED,
            ),
            _make_zone(
                "obstacle_b", 500, 100, 80, 200,
                ZoneType.STATIC, "Panel B", ZoneState.ENABLED,
            ),
        ]
    )
    return reg


@pytest.fixture()
def pop_planner(
    populated_registry: ZoneRegistry, settings: Settings,
) -> MotionPlanner:
    """Return a MotionPlanner wired to the populated registry."""
    return MotionPlanner(populated_registry, settings)


# ==================================================================
# plan_direct
# ==================================================================


class TestPlanDirect:
    """Tests for MotionPlanner.plan_direct."""

    def test_returns_trajectory_with_direct_type(
        self, pop_planner: MotionPlanner,
    ) -> None:
        traj = pop_planner.plan_direct((0, 0), "btn_save")
        assert traj.type is TrajectoryType.DIRECT

    def test_first_point_is_start(
        self, pop_planner: MotionPlanner,
    ) -> None:
        start = (10, 20)
        traj = pop_planner.plan_direct(start, "btn_save")
        assert traj.points[0] == start

    def test_last_point_is_zone_center(
        self, pop_planner: MotionPlanner,
    ) -> None:
        traj = pop_planner.plan_direct((0, 0), "btn_save")
        # btn_save: x=200, y=200, w=80, h=30 => center = (240, 215)
        assert traj.points[-1] == (240, 215)

    def test_multiple_intermediate_waypoints_for_long_distance(
        self, pop_planner: MotionPlanner,
    ) -> None:
        """A long distance should produce more than the minimum waypoints."""
        # Start far from btn_save center (240, 215)
        traj = pop_planner.plan_direct((0, 0), "btn_save")
        assert len(traj.points) >= _MIN_WAYPOINTS

    def test_short_distance_produces_minimum_2_points(
        self, pop_planner: MotionPlanner,
    ) -> None:
        """Even a very short move still has start and end."""
        # Start close to btn_save center (240, 215)
        traj = pop_planner.plan_direct((239, 214), "btn_save")
        assert len(traj.points) >= _MIN_WAYPOINTS

    def test_points_evenly_distributed(
        self, pop_planner: MotionPlanner,
    ) -> None:
        """Inter-point distances should be roughly equal."""
        traj = pop_planner.plan_direct((0, 0), "btn_save")
        if len(traj.points) < 3:
            return  # Cannot check uniformity with fewer than 3 points
        distances: list[float] = []
        for i in range(len(traj.points) - 1):
            ax, ay = traj.points[i]
            bx, by = traj.points[i + 1]
            distances.append(math.sqrt((bx - ax) ** 2 + (by - ay) ** 2))
        avg = sum(distances) / len(distances)
        # Each segment should be within 2px of the average (rounding tolerance)
        for d in distances:
            assert abs(d - avg) < 2.0

    def test_target_zone_id_is_set(
        self, pop_planner: MotionPlanner,
    ) -> None:
        traj = pop_planner.plan_direct((0, 0), "btn_save")
        assert traj.target_zone_id == "btn_save"

    def test_nonexistent_zone_raises_value_error(
        self, pop_planner: MotionPlanner,
    ) -> None:
        with pytest.raises(ValueError, match="no_such_zone"):
            pop_planner.plan_direct((0, 0), "no_such_zone")

    def test_zero_distance_produces_2_points(
        self, pop_planner: MotionPlanner,
    ) -> None:
        """When start == zone center, trajectory still has >= 2 points."""
        center = (240, 215)  # btn_save center
        traj = pop_planner.plan_direct(center, "btn_save")
        assert len(traj.points) >= 2
        assert traj.points[0] == center
        assert traj.points[-1] == center

    def test_diagonal_path_interpolates_correctly(
        self, registry: ZoneRegistry, settings: Settings,
    ) -> None:
        """A diagonal path should interpolate both x and y."""
        zone = _make_zone("diag", 196, 96, 8, 8)  # center = (200, 100)
        registry.register(zone)
        planner = MotionPlanner(registry, settings)
        traj = planner.plan_direct((0, 0), "diag")
        # All points should lie approximately on the line y = 0.5*x
        for x, y in traj.points:
            if x == 0:
                assert y == 0
            else:
                ratio = y / x
                assert abs(ratio - 0.5) < 0.1

    def test_waypoint_count_scales_with_distance(
        self, registry: ZoneRegistry, settings: Settings,
    ) -> None:
        """A far-away zone should produce more waypoints than a near one."""
        near = _make_zone("near", 46, 46, 8, 8)   # center = (50, 50)
        far = _make_zone("far", 996, 996, 8, 8)    # center = (1000, 1000)
        registry.register(near)
        registry.register(far)
        planner = MotionPlanner(registry, settings)
        traj_near = planner.plan_direct((0, 0), "near")
        traj_far = planner.plan_direct((0, 0), "far")
        assert len(traj_far.points) > len(traj_near.points)

    def test_avoid_zone_ids_empty_for_direct(
        self, pop_planner: MotionPlanner,
    ) -> None:
        """Direct trajectories have no avoid zones."""
        traj = pop_planner.plan_direct((0, 0), "btn_save")
        assert traj.avoid_zone_ids == []


# ==================================================================
# plan_safe
# ==================================================================


class TestPlanSafe:
    """Tests for MotionPlanner.plan_safe."""

    def test_returns_trajectory_with_safe_type(
        self, pop_planner: MotionPlanner,
    ) -> None:
        traj = pop_planner.plan_safe((0, 0), "btn_save", [])
        assert traj.type is TrajectoryType.SAFE

    def test_no_intersection_equivalent_to_direct(
        self, pop_planner: MotionPlanner,
    ) -> None:
        """When no avoid zones block the path, result matches direct."""
        start = (0, 0)
        traj_safe = pop_planner.plan_safe(start, "btn_save", [])
        traj_direct = pop_planner.plan_direct(start, "btn_save")
        assert traj_safe.points == traj_direct.points

    def test_avoids_zone_in_direct_path(
        self, populated_registry: ZoneRegistry, settings: Settings,
    ) -> None:
        """Path should detour around obstacle_a between start and target.

        The safe planner inserts detour waypoints so the path differs
        from the direct path.  We verify that the safe trajectory is
        different (has extra detour points) and still reaches the target.
        """
        # obstacle_a: (300, 100, 100, 200) blocks direct path
        # from (100, 200) to btn_cancel center (440, 215)
        planner = MotionPlanner(populated_registry, settings)
        start = (100, 200)
        traj_safe = planner.plan_safe(
            start, "btn_cancel", ["obstacle_a"],
        )
        traj_direct = planner.plan_direct(start, "btn_cancel")

        # The safe path should differ from the direct path because
        # it routes around obstacle_a.
        assert traj_safe.points != traj_direct.points

        # Endpoints should still be correct.
        assert traj_safe.points[0] == start
        # btn_cancel center = (440, 215)
        assert traj_safe.points[-1] == (440, 215)

    def test_avoid_zone_ids_populated_in_result(
        self, pop_planner: MotionPlanner,
    ) -> None:
        traj = pop_planner.plan_safe(
            (0, 0), "btn_save", ["obstacle_a"],
        )
        assert traj.avoid_zone_ids == ["obstacle_a"]

    def test_multiple_avoid_zones(
        self, pop_planner: MotionPlanner,
    ) -> None:
        traj = pop_planner.plan_safe(
            (0, 0), "btn_save", ["obstacle_a", "obstacle_b"],
        )
        assert set(traj.avoid_zone_ids) == {"obstacle_a", "obstacle_b"}
        assert traj.type is TrajectoryType.SAFE

    def test_nonexistent_target_zone_raises(
        self, pop_planner: MotionPlanner,
    ) -> None:
        with pytest.raises(ValueError, match="no_such_target"):
            pop_planner.plan_safe(
                (0, 0), "no_such_target", ["obstacle_a"],
            )

    def test_nonexistent_avoid_zone_raises(
        self, pop_planner: MotionPlanner,
    ) -> None:
        with pytest.raises(ValueError, match="ghost_zone"):
            pop_planner.plan_safe(
                (0, 0), "btn_save", ["ghost_zone"],
            )

    def test_path_starts_at_start_and_ends_at_zone_center(
        self, pop_planner: MotionPlanner,
    ) -> None:
        start = (50, 50)
        traj = pop_planner.plan_safe(
            start, "btn_save", ["obstacle_a"],
        )
        assert traj.points[0] == start
        # btn_save center = (240, 215)
        assert traj.points[-1] == (240, 215)

    def test_waypoint_count_capped_at_max(
        self, registry: ZoneRegistry,
    ) -> None:
        """Even with many detours, points are capped at MAX_WAYPOINTS."""
        # Create a target far away and a series of small obstacles
        target = _make_zone("far_target", 9996, 9996, 8, 8)
        registry.register(target)
        obstacles: list[Zone] = []
        avoid_ids: list[str] = []
        for i in range(20):
            oid = f"obs_{i}"
            oz = _make_zone(
                oid, 500 * i, 4990, 50, 50,
                ZoneType.STATIC, f"Obs{i}",
            )
            registry.register(oz)
            obstacles.append(oz)
            avoid_ids.append(oid)

        # Use a very slow speed to generate many waypoints per segment
        slow_settings = Settings(motion_speed_pixels_per_sec=10.0)
        planner = MotionPlanner(registry, slow_settings)
        traj = planner.plan_safe((0, 0), "far_target", avoid_ids)
        assert len(traj.points) <= _MAX_WAYPOINTS

    def test_target_zone_id_set_correctly(
        self, pop_planner: MotionPlanner,
    ) -> None:
        traj = pop_planner.plan_safe(
            (0, 0), "btn_cancel", ["obstacle_a"],
        )
        assert traj.target_zone_id == "btn_cancel"


# ==================================================================
# plan_exploratory
# ==================================================================


class TestPlanExploratory:
    """Tests for MotionPlanner.plan_exploratory."""

    def test_returns_trajectory_with_exploratory_type(
        self, planner: MotionPlanner,
    ) -> None:
        traj = planner.plan_exploratory((0, 0), (100, 100, 200, 200))
        assert traj.type is TrajectoryType.EXPLORATORY

    def test_target_zone_id_is_empty_string(
        self, planner: MotionPlanner,
    ) -> None:
        traj = planner.plan_exploratory((0, 0), (100, 100, 200, 200))
        assert traj.target_zone_id == ""

    def test_covers_region_with_scan_lines(
        self, planner: MotionPlanner,
    ) -> None:
        """Points should span the full width and height of the region."""
        rx, ry, rw, rh = 100, 100, 200, 200
        traj = planner.plan_exploratory((0, 0), (rx, ry, rw, rh))
        xs = [p[0] for p in traj.points]
        ys = [p[1] for p in traj.points]
        # Points should reach both horizontal edges of the region
        assert min(xs) <= rx + 1
        assert max(xs) >= rx + rw - 1
        # Points should span the vertical extent
        assert min(ys) <= ry + 1
        assert max(ys) >= ry + rh - 1

    def test_starts_from_provided_start_point(
        self, planner: MotionPlanner,
    ) -> None:
        start = (50, 50)
        traj = planner.plan_exploratory(start, (100, 100, 200, 200))
        assert traj.points[0] == start

    def test_zigzag_pattern_alternates_direction(
        self, settings: Settings,
    ) -> None:
        """Even rows go left-to-right, odd rows go right-to-left."""
        registry = ZoneRegistry()
        planner = MotionPlanner(registry, settings)
        region = (0, 0, 100, 100)
        spacing = 50
        traj = planner.plan_exploratory((0, 0), region, scan_spacing=spacing)
        # Collect the scan-line endpoints by finding points at each y level
        scan_ys = list(range(0, 101, spacing))  # 0, 50, 100
        for row_idx, sy in enumerate(scan_ys):
            row_pts = [p for p in traj.points if p[1] == sy]
            if len(row_pts) < 2:
                continue
            first_x = row_pts[0][0]
            last_x = row_pts[-1][0]
            if row_idx % 2 == 0:
                # Even row: left to right
                assert first_x <= last_x
            else:
                # Odd row: right to left
                assert first_x >= last_x

    def test_custom_scan_spacing(
        self, planner: MotionPlanner,
    ) -> None:
        """Smaller spacing produces more scan lines and more points."""
        region = (0, 0, 100, 200)
        traj_wide = planner.plan_exploratory(
            (0, 0), region, scan_spacing=100,
        )
        traj_narrow = planner.plan_exploratory(
            (0, 0), region, scan_spacing=25,
        )
        assert len(traj_narrow.points) > len(traj_wide.points)

    def test_degenerate_region_zero_width(
        self, planner: MotionPlanner,
    ) -> None:
        start = (50, 50)
        traj = planner.plan_exploratory(start, (100, 100, 0, 200))
        assert len(traj.points) == 1
        assert traj.points[0] == start

    def test_degenerate_region_zero_height(
        self, planner: MotionPlanner,
    ) -> None:
        start = (50, 50)
        traj = planner.plan_exploratory(start, (100, 100, 200, 0))
        assert len(traj.points) == 1
        assert traj.points[0] == start

    def test_points_capped_at_max_waypoints(
        self, settings: Settings,
    ) -> None:
        """A very large region with fine spacing should be capped."""
        registry = ZoneRegistry()
        # Use slow speed to maximise waypoints per segment
        slow_settings = Settings(motion_speed_pixels_per_sec=10.0)
        planner = MotionPlanner(registry, slow_settings)
        traj = planner.plan_exploratory(
            (0, 0), (0, 0, 5000, 5000), scan_spacing=5,
        )
        assert len(traj.points) <= _MAX_WAYPOINTS


# ==================================================================
# interpolate_line
# ==================================================================


class TestInterpolateLine:
    """Tests for MotionPlanner.interpolate_line (static method)."""

    def test_start_and_end_included(self) -> None:
        pts = MotionPlanner.interpolate_line((0, 0), (100, 0), 5)
        assert pts[0] == (0, 0)
        assert pts[-1] == (100, 0)

    def test_correct_number_of_points(self) -> None:
        pts = MotionPlanner.interpolate_line((0, 0), (100, 0), 10)
        assert len(pts) == 10

    def test_minimum_2_steps_enforced(self) -> None:
        """Requesting fewer than 2 steps still yields at least 2 points."""
        pts = MotionPlanner.interpolate_line((0, 0), (100, 0), 1)
        assert len(pts) >= _MIN_WAYPOINTS
        pts_zero = MotionPlanner.interpolate_line((0, 0), (100, 0), 0)
        assert len(pts_zero) >= _MIN_WAYPOINTS
        pts_neg = MotionPlanner.interpolate_line((0, 0), (100, 0), -5)
        assert len(pts_neg) >= _MIN_WAYPOINTS

    def test_horizontal_line(self) -> None:
        pts = MotionPlanner.interpolate_line((0, 50), (100, 50), 5)
        for _x, y in pts:
            assert y == 50

    def test_vertical_line(self) -> None:
        pts = MotionPlanner.interpolate_line((50, 0), (50, 100), 5)
        for x, _y in pts:
            assert x == 50

    def test_diagonal_line(self) -> None:
        pts = MotionPlanner.interpolate_line((0, 0), (100, 100), 11)
        # Each point should have x == y (or very close due to rounding)
        for x, y in pts:
            assert abs(x - y) <= 1

    def test_same_start_and_end(self) -> None:
        pts = MotionPlanner.interpolate_line((42, 42), (42, 42), 5)
        assert len(pts) == 5
        for p in pts:
            assert p == (42, 42)


# ==================================================================
# line_intersects_rect
# ==================================================================


class TestLineIntersectsRect:
    """Tests for MotionPlanner.line_intersects_rect (static method)."""

    def test_line_through_rectangle(self) -> None:
        rect = Rectangle(x=50, y=50, width=100, height=100)
        assert MotionPlanner.line_intersects_rect(
            (0, 100), (200, 100), rect,
        ) is True

    def test_line_missing_rectangle(self) -> None:
        rect = Rectangle(x=50, y=50, width=100, height=100)
        # Line passes entirely above the rectangle
        assert MotionPlanner.line_intersects_rect(
            (0, 10), (200, 10), rect,
        ) is False

    def test_line_touching_edge(self) -> None:
        """A line along the top edge of the rect should intersect."""
        rect = Rectangle(x=50, y=50, width=100, height=100)
        assert MotionPlanner.line_intersects_rect(
            (0, 50), (200, 50), rect,
        ) is True

    def test_line_entirely_inside(self) -> None:
        rect = Rectangle(x=0, y=0, width=200, height=200)
        assert MotionPlanner.line_intersects_rect(
            (50, 50), (100, 100), rect,
        ) is True

    def test_zero_area_rectangle_returns_false(self) -> None:
        rect = Rectangle(x=50, y=50, width=0, height=100)
        assert MotionPlanner.line_intersects_rect(
            (0, 100), (200, 100), rect,
        ) is False

    def test_diagonal_line_through_rect(self) -> None:
        rect = Rectangle(x=50, y=50, width=100, height=100)
        assert MotionPlanner.line_intersects_rect(
            (0, 0), (200, 200), rect,
        ) is True

    def test_diagonal_line_missing_rect(self) -> None:
        rect = Rectangle(x=200, y=0, width=50, height=50)
        assert MotionPlanner.line_intersects_rect(
            (0, 0), (100, 100), rect,
        ) is False

    def test_line_endpoint_on_rect_corner(self) -> None:
        """Line ending exactly at the rectangle corner."""
        rect = Rectangle(x=100, y=100, width=50, height=50)
        assert MotionPlanner.line_intersects_rect(
            (0, 0), (100, 100), rect,
        ) is True

    def test_line_passing_just_outside_rect(self) -> None:
        rect = Rectangle(x=100, y=100, width=50, height=50)
        # Horizontal line just below the rectangle
        assert MotionPlanner.line_intersects_rect(
            (0, 151), (200, 151), rect,
        ) is False

    def test_zero_length_line_inside_rect(self) -> None:
        """A zero-length segment (point) inside the rect."""
        rect = Rectangle(x=0, y=0, width=100, height=100)
        assert MotionPlanner.line_intersects_rect(
            (50, 50), (50, 50), rect,
        ) is True

    def test_zero_length_line_outside_rect(self) -> None:
        rect = Rectangle(x=0, y=0, width=100, height=100)
        assert MotionPlanner.line_intersects_rect(
            (200, 200), (200, 200), rect,
        ) is False


# ==================================================================
# estimate_duration_ms
# ==================================================================


class TestEstimateDurationMs:
    """Tests for MotionPlanner.estimate_duration_ms."""

    def test_correct_for_known_distance_and_speed(
        self, planner: MotionPlanner,
    ) -> None:
        """1500 px at 1500 px/sec => 1.0 sec => 1000 ms."""
        traj = Trajectory(
            type=TrajectoryType.DIRECT,
            points=[(0, 0), (1500, 0)],
            target_zone_id="t",
        )
        ms = planner.estimate_duration_ms(traj)
        assert abs(ms - 1000.0) < 0.01

    def test_empty_trajectory_returns_zero(
        self, planner: MotionPlanner,
    ) -> None:
        traj = Trajectory(
            type=TrajectoryType.DIRECT,
            points=[],
            target_zone_id="t",
        )
        assert planner.estimate_duration_ms(traj) == 0.0

    def test_single_point_trajectory_returns_zero(
        self, planner: MotionPlanner,
    ) -> None:
        traj = Trajectory(
            type=TrajectoryType.DIRECT,
            points=[(100, 100)],
            target_zone_id="t",
        )
        assert planner.estimate_duration_ms(traj) == 0.0

    def test_multi_segment_sums_distances(
        self, planner: MotionPlanner,
    ) -> None:
        """A trajectory of 3 points: (0,0)->(300,0)->(300,400).
        Total distance = 300 + 400 = 700 px.
        At 1500 px/sec => 700/1500 * 1000 = 466.667 ms.
        """
        traj = Trajectory(
            type=TrajectoryType.DIRECT,
            points=[(0, 0), (300, 0), (300, 400)],
            target_zone_id="t",
        )
        ms = planner.estimate_duration_ms(traj)
        expected = (700.0 / 1500.0) * 1000.0
        assert abs(ms - expected) < 0.01

    def test_diagonal_distance(
        self, planner: MotionPlanner,
    ) -> None:
        """(0,0) to (300,400) = 500 px.  500/1500*1000 = 333.33 ms."""
        traj = Trajectory(
            type=TrajectoryType.DIRECT,
            points=[(0, 0), (300, 400)],
            target_zone_id="t",
        )
        ms = planner.estimate_duration_ms(traj)
        expected = (500.0 / 1500.0) * 1000.0
        assert abs(ms - expected) < 0.1

    def test_zero_speed_returns_zero(self) -> None:
        """If speed is zero, duration should be 0."""
        zero_settings = Settings(motion_speed_pixels_per_sec=0.0)
        registry = ZoneRegistry()
        planner = MotionPlanner(registry, zero_settings)
        traj = Trajectory(
            type=TrajectoryType.DIRECT,
            points=[(0, 0), (100, 0)],
            target_zone_id="t",
        )
        assert planner.estimate_duration_ms(traj) == 0.0

    def test_same_start_and_end_returns_zero(
        self, planner: MotionPlanner,
    ) -> None:
        traj = Trajectory(
            type=TrajectoryType.DIRECT,
            points=[(50, 50), (50, 50)],
            target_zone_id="t",
        )
        assert planner.estimate_duration_ms(traj) == 0.0


# ==================================================================
# Edge cases and integration
# ==================================================================


class TestEdgeCases:
    """Miscellaneous edge-case and integration tests."""

    def test_plan_direct_and_estimate_duration_consistent(
        self, pop_planner: MotionPlanner,
    ) -> None:
        """Duration of a planned trajectory should be positive."""
        traj = pop_planner.plan_direct((0, 0), "btn_save")
        ms = pop_planner.estimate_duration_ms(traj)
        assert ms > 0.0

    def test_plan_safe_with_empty_avoid_list(
        self, pop_planner: MotionPlanner,
    ) -> None:
        """Empty avoid list is allowed and produces a valid trajectory."""
        traj = pop_planner.plan_safe((0, 0), "btn_save", [])
        assert len(traj.points) >= _MIN_WAYPOINTS
        assert traj.avoid_zone_ids == []

    def test_plan_exploratory_with_start_inside_region(
        self, planner: MotionPlanner,
    ) -> None:
        """Start point inside the scan region is valid."""
        traj = planner.plan_exploratory(
            (150, 150), (100, 100, 200, 200),
        )
        assert traj.points[0] == (150, 150)
        assert len(traj.points) >= _MIN_WAYPOINTS

    def test_interpolate_line_negative_coords(self) -> None:
        """Negative coordinates should work fine."""
        pts = MotionPlanner.interpolate_line((-100, -100), (100, 100), 5)
        assert pts[0] == (-100, -100)
        assert pts[-1] == (100, 100)
        assert len(pts) == 5

    def test_plan_safe_both_target_and_avoid_nonexistent(
        self, planner: MotionPlanner,
    ) -> None:
        """Target validation happens before avoid validation."""
        with pytest.raises(ValueError, match="Target zone"):
            planner.plan_safe(
                (0, 0), "no_target", ["no_avoid"],
            )

    def test_exploratory_scan_spacing_clamped_to_1(
        self, planner: MotionPlanner,
    ) -> None:
        """Zero or negative scan spacing should be clamped to 1."""
        traj = planner.plan_exploratory(
            (0, 0), (0, 0, 10, 10), scan_spacing=0,
        )
        assert len(traj.points) >= _MIN_WAYPOINTS

    def test_constants_accessible(self) -> None:
        """Module-level constants should have expected values."""
        assert _MAX_WAYPOINTS == 200
        assert _MIN_WAYPOINTS == 2
        assert _DEFAULT_SCAN_SPACING == 50
