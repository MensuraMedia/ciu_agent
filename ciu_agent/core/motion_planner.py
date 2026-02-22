"""Motion planner: generates cursor movement trajectories.

The MotionPlanner produces waypoint paths that the BrushController
follows via the platform input layer.  Three planning strategies are
supported:

* **Direct** -- a straight line to the target zone center.
* **Safe** -- a path that avoids crossing specified zones.
* **Exploratory** -- a lawnmower sweep across a rectangular region.

This module depends only on ``ciu_agent.models``,
``ciu_agent.core.zone_registry``, and ``ciu_agent.config.settings``.
It does not import any other ``core/`` modules.
"""

from __future__ import annotations

import math

from ciu_agent.config.settings import Settings
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.actions import Trajectory, TrajectoryType
from ciu_agent.models.zone import Rectangle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ASSUMED_FPS: int = 60
"""Frame rate assumed when converting speed into per-frame step count."""

_MAX_WAYPOINTS: int = 200
"""Upper bound on waypoints in a single trajectory segment."""

_MIN_WAYPOINTS: int = 2
"""Every trajectory has at least a start and an end point."""

_DEFAULT_SCAN_SPACING: int = 50
"""Pixel gap between scan lines in an exploratory sweep."""


class MotionPlanner:
    """Generates cursor movement trajectories for the Brush Controller.

    The planner looks up target and obstacle zones in the shared
    ``ZoneRegistry`` and uses the configured motion speed from
    ``Settings`` to interpolate waypoints at a rate suitable for
    60 fps execution.

    Example::

        planner = MotionPlanner(registry, settings)
        traj = planner.plan_direct((100, 100), "btn_save")
        for x, y in traj.points:
            platform.move_cursor(x, y)
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, registry: ZoneRegistry, settings: Settings) -> None:
        """Initialise the motion planner.

        Args:
            registry: Zone registry used to look up target and
                obstacle zones by ID.
            settings: Application settings (uses
                ``motion_speed_pixels_per_sec``).
        """
        self._registry = registry
        self._settings = settings

    # ------------------------------------------------------------------
    # Core planning methods
    # ------------------------------------------------------------------

    def plan_direct(
        self,
        start: tuple[int, int],
        target_zone_id: str,
    ) -> Trajectory:
        """Generate a straight-line trajectory to a target zone.

        The path runs from *start* to the center of the zone
        identified by *target_zone_id*.  Waypoints are evenly
        distributed along the line at intervals determined by the
        configured motion speed and the assumed 60 fps tick rate.

        Args:
            start: Current cursor position ``(x, y)``.
            target_zone_id: ID of the destination zone in the
                registry.

        Returns:
            A ``Trajectory`` with ``type=DIRECT`` and interpolated
            waypoints.

        Raises:
            ValueError: If *target_zone_id* is not found in the
                registry.
        """
        zone = self._registry.get(target_zone_id)
        if zone is None:
            raise ValueError(f"Target zone '{target_zone_id}' not found in registry")

        end = zone.bounds.center()
        num_steps = self._steps_for_distance(self._distance(start, end))
        points = self.interpolate_line(start, end, num_steps)

        return Trajectory(
            type=TrajectoryType.DIRECT,
            points=points,
            target_zone_id=target_zone_id,
        )

    def plan_safe(
        self,
        start: tuple[int, int],
        target_zone_id: str,
        avoid_zone_ids: list[str],
    ) -> Trajectory:
        """Generate a trajectory that avoids crossing specified zones.

        If the direct path from *start* to the target zone center
        does not intersect any of the avoid zones, the result is
        equivalent to ``plan_direct``.  Otherwise the planner routes
        around the blocking zone by offsetting perpendicular to the
        line of travel past the nearer edge.

        Args:
            start: Current cursor position ``(x, y)``.
            target_zone_id: ID of the destination zone.
            avoid_zone_ids: IDs of zones the path must not cross.

        Returns:
            A ``Trajectory`` with ``type=SAFE`` and
            ``avoid_zone_ids`` populated.

        Raises:
            ValueError: If *target_zone_id* or any ID in
                *avoid_zone_ids* is not found in the registry.
        """
        target_zone = self._registry.get(target_zone_id)
        if target_zone is None:
            raise ValueError(f"Target zone '{target_zone_id}' not found in registry")

        avoid_rects: list[tuple[str, Rectangle]] = []
        for zid in avoid_zone_ids:
            zone = self._registry.get(zid)
            if zone is None:
                raise ValueError(f"Avoid zone '{zid}' not found in registry")
            avoid_rects.append((zid, zone.bounds))

        end = target_zone.bounds.center()
        waypoints = self._route_around(start, end, avoid_rects)

        # Interpolate each leg of the route and merge.
        all_points: list[tuple[int, int]] = []
        for i in range(len(waypoints) - 1):
            seg_start = waypoints[i]
            seg_end = waypoints[i + 1]
            num_steps = self._steps_for_distance(self._distance(seg_start, seg_end))
            seg_points = self.interpolate_line(seg_start, seg_end, num_steps)
            if all_points:
                # Avoid duplicating the junction point.
                seg_points = seg_points[1:]
            all_points.extend(seg_points)

        # Enforce global waypoint limits.
        if len(all_points) > _MAX_WAYPOINTS:
            all_points = self._downsample(all_points, _MAX_WAYPOINTS)

        return Trajectory(
            type=TrajectoryType.SAFE,
            points=all_points,
            target_zone_id=target_zone_id,
            avoid_zone_ids=list(avoid_zone_ids),
        )

    def plan_exploratory(
        self,
        start: tuple[int, int],
        region: tuple[int, int, int, int],
        scan_spacing: int = _DEFAULT_SCAN_SPACING,
    ) -> Trajectory:
        """Generate a lawnmower sweep over a rectangular region.

        The cursor moves in horizontal scan lines across *region*,
        alternating direction on each row to minimise travel.

        Args:
            start: Current cursor position ``(x, y)``.
            region: The area to scan as ``(x, y, width, height)``.
            scan_spacing: Vertical gap in pixels between scan lines.
                Defaults to 50.

        Returns:
            A ``Trajectory`` with ``type=EXPLORATORY`` and
            ``target_zone_id=""``.
        """
        rx, ry, rw, rh = region
        if rw <= 0 or rh <= 0:
            # Degenerate region -- return a single-point trajectory.
            return Trajectory(
                type=TrajectoryType.EXPLORATORY,
                points=[start],
                target_zone_id="",
            )

        scan_spacing = max(1, scan_spacing)

        # Build scan-line endpoints.
        scan_points: list[tuple[int, int]] = []
        left = rx
        right = rx + rw
        y = ry
        row_index = 0
        while y <= ry + rh:
            if row_index % 2 == 0:
                scan_points.append((left, y))
                scan_points.append((right, y))
            else:
                scan_points.append((right, y))
                scan_points.append((left, y))
            y += scan_spacing
            row_index += 1

        if not scan_points:
            scan_points.append((rx, ry))

        # Prepend a leg from start to the first scan point.
        all_points: list[tuple[int, int]] = []
        first_scan = scan_points[0]
        lead_in_steps = self._steps_for_distance(self._distance(start, first_scan))
        lead_in = self.interpolate_line(start, first_scan, lead_in_steps)
        all_points.extend(lead_in)

        # Interpolate each scan-line segment.
        for i in range(len(scan_points) - 1):
            seg_start = scan_points[i]
            seg_end = scan_points[i + 1]
            num_steps = self._steps_for_distance(self._distance(seg_start, seg_end))
            seg = self.interpolate_line(seg_start, seg_end, num_steps)
            # Drop the first point to avoid duplicating the junction.
            all_points.extend(seg[1:])

        if len(all_points) > _MAX_WAYPOINTS:
            all_points = self._downsample(all_points, _MAX_WAYPOINTS)

        return Trajectory(
            type=TrajectoryType.EXPLORATORY,
            points=all_points,
            target_zone_id="",
        )

    # ------------------------------------------------------------------
    # Helper / utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def interpolate_line(
        start: tuple[int, int],
        end: tuple[int, int],
        num_steps: int,
    ) -> list[tuple[int, int]]:
        """Linearly interpolate between two points.

        Args:
            start: Starting ``(x, y)`` coordinate.
            end: Ending ``(x, y)`` coordinate.
            num_steps: Total number of waypoints to produce, including
                *start* and *end*.  Clamped to a minimum of 2.

        Returns:
            A list of ``(x, y)`` integer waypoints from *start* to
            *end* inclusive.
        """
        num_steps = max(_MIN_WAYPOINTS, num_steps)
        if num_steps == 1:
            return [start]

        sx, sy = start
        ex, ey = end
        points: list[tuple[int, int]] = []
        for i in range(num_steps):
            t = i / (num_steps - 1)
            x = round(sx + (ex - sx) * t)
            y = round(sy + (ey - sy) * t)
            points.append((x, y))
        return points

    @staticmethod
    def line_intersects_rect(
        p1: tuple[int, int],
        p2: tuple[int, int],
        rect: Rectangle,
    ) -> bool:
        """Test whether a line segment intersects an axis-aligned rectangle.

        Uses the Liang-Barsky clipping algorithm to determine whether
        any portion of the segment from *p1* to *p2* passes through
        *rect*.

        Args:
            p1: First endpoint of the line segment ``(x, y)``.
            p2: Second endpoint of the line segment ``(x, y)``.
            rect: The axis-aligned bounding rectangle.

        Returns:
            ``True`` if the segment intersects or is contained by the
            rectangle.
        """
        if rect.area() == 0:
            return False

        x1, y1 = float(p1[0]), float(p1[1])
        x2, y2 = float(p2[0]), float(p2[1])

        dx = x2 - x1
        dy = y2 - y1

        # Rectangle edges.
        x_min = float(rect.x)
        x_max = float(rect.x + rect.width)
        y_min = float(rect.y)
        y_max = float(rect.y + rect.height)

        # Liang-Barsky parameters: -dx, +dx, -dy, +dy
        p = [-dx, dx, -dy, dy]
        q = [
            x1 - x_min,
            x_max - x1,
            y1 - y_min,
            y_max - y1,
        ]

        t_enter = 0.0
        t_exit = 1.0

        for pi, qi in zip(p, q):
            if pi == 0.0:
                # Line is parallel to this edge pair.
                if qi < 0.0:
                    return False
            else:
                t = qi / pi
                if pi < 0.0:
                    t_enter = max(t_enter, t)
                else:
                    t_exit = min(t_exit, t)
                if t_enter > t_exit:
                    return False

        return t_enter <= t_exit

    def estimate_duration_ms(self, trajectory: Trajectory) -> float:
        """Estimate traversal time in milliseconds for a trajectory.

        The estimate is based on the total Euclidean path length and
        the configured ``motion_speed_pixels_per_sec``.

        Args:
            trajectory: The trajectory to measure.

        Returns:
            Estimated duration in milliseconds.  Returns ``0.0`` for
            trajectories with fewer than two points.
        """
        if len(trajectory.points) < 2:
            return 0.0

        total_distance = 0.0
        for i in range(len(trajectory.points) - 1):
            total_distance += self._distance(trajectory.points[i], trajectory.points[i + 1])

        speed = self._settings.motion_speed_pixels_per_sec
        if speed <= 0.0:
            return 0.0

        return (total_distance / speed) * 1000.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _distance(
        a: tuple[int, int],
        b: tuple[int, int],
    ) -> float:
        """Euclidean distance between two points."""
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        return math.sqrt(dx * dx + dy * dy)

    def _steps_for_distance(self, distance: float) -> int:
        """Calculate the number of interpolation steps for a distance.

        Uses the configured motion speed and the assumed 60 fps tick
        rate to determine how many waypoints are needed.

        Args:
            distance: Euclidean distance in pixels.

        Returns:
            An integer step count clamped to
            [``_MIN_WAYPOINTS``, ``_MAX_WAYPOINTS``].
        """
        speed = self._settings.motion_speed_pixels_per_sec
        if speed <= 0.0 or distance <= 0.0:
            return _MIN_WAYPOINTS

        # Time in seconds to traverse the distance.
        travel_seconds = distance / speed
        # Number of frames at assumed FPS.
        steps = max(
            _MIN_WAYPOINTS,
            min(_MAX_WAYPOINTS, round(travel_seconds * _ASSUMED_FPS)),
        )
        return steps

    def _route_around(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        avoid_rects: list[tuple[str, Rectangle]],
        _depth: int = 0,
    ) -> list[tuple[int, int]]:
        """Recursively build waypoints that avoid blocking rectangles.

        If the direct segment from *start* to *end* is clear, returns
        ``[start, end]``.  Otherwise it detects the first blocking
        rectangle and inserts a detour waypoint around the nearer
        edge, then recurses on the resulting sub-segments.

        Args:
            start: Segment start ``(x, y)``.
            end: Segment end ``(x, y)``.
            avoid_rects: List of ``(zone_id, Rectangle)`` pairs to
                avoid.
            _depth: Internal recursion depth guard.

        Returns:
            Ordered list of waypoints from *start* to *end*.
        """
        _MAX_DEPTH = 10
        if _depth >= _MAX_DEPTH:
            return [start, end]

        # Find the first blocking rectangle along the segment.
        blocker: Rectangle | None = None
        for _zid, rect in avoid_rects:
            if self.line_intersects_rect(start, end, rect):
                blocker = rect
                break

        if blocker is None:
            return [start, end]

        # Determine a detour point around the blocker.
        detour = self._detour_point(start, end, blocker)

        # Recurse on the two sub-segments.
        first_leg = self._route_around(start, detour, avoid_rects, _depth + 1)
        second_leg = self._route_around(detour, end, avoid_rects, _depth + 1)

        # Merge, dropping the duplicate junction point.
        return first_leg + second_leg[1:]

    @staticmethod
    def _detour_point(
        start: tuple[int, int],
        end: tuple[int, int],
        blocker: Rectangle,
    ) -> tuple[int, int]:
        """Choose a waypoint that routes around a blocking rectangle.

        The detour goes around whichever edge of the rectangle is
        closer to the midpoint of the segment.  A small margin (half
        the larger dimension or 10 px, whichever is smaller) keeps
        the path from grazing the rectangle edge.

        Args:
            start: Segment start ``(x, y)``.
            end: Segment end ``(x, y)``.
            blocker: The rectangle to route around.

        Returns:
            A single ``(x, y)`` waypoint that lies outside *blocker*.
        """
        margin = min(10, max(blocker.width, blocker.height) // 2 + 1)

        mid_x = (start[0] + end[0]) / 2.0
        mid_y = (start[1] + end[1]) / 2.0

        bx = blocker.x
        by = blocker.y
        bw = blocker.width
        bh = blocker.height

        # Distances from midpoint to each edge of the blocker.
        dist_left = abs(mid_x - bx)
        dist_right = abs(mid_x - (bx + bw))
        dist_top = abs(mid_y - by)
        dist_bottom = abs(mid_y - (by + bh))

        min_dist = min(dist_left, dist_right, dist_top, dist_bottom)

        # Route past the closest edge, keeping the margin.
        bcx, bcy = blocker.center()

        if min_dist == dist_top:
            # Go above the blocker.
            return (bcx, by - margin)
        elif min_dist == dist_bottom:
            # Go below the blocker.
            return (bcx, by + bh + margin)
        elif min_dist == dist_left:
            # Go left of the blocker.
            return (bx - margin, bcy)
        else:
            # Go right of the blocker.
            return (bx + bw + margin, bcy)

    @staticmethod
    def _downsample(
        points: list[tuple[int, int]],
        max_count: int,
    ) -> list[tuple[int, int]]:
        """Uniformly downsample a point list while keeping endpoints.

        Args:
            points: Original waypoint list.
            max_count: Maximum number of points to keep (>= 2).

        Returns:
            A shortened list that preserves the first and last
            points.
        """
        if len(points) <= max_count or max_count < 2:
            return list(points)

        result: list[tuple[int, int]] = [points[0]]
        step = (len(points) - 1) / (max_count - 1)
        for i in range(1, max_count - 1):
            idx = round(i * step)
            result.append(points[idx])
        result.append(points[-1])
        return result
