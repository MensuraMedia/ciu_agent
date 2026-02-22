"""Heuristic classifier for screen changes detected by Tier 0 diffing.

Routes each ``DiffResult`` from the ``CaptureEngine`` to the appropriate
analysis tier (0, 1, or 2) by inspecting the size, position, and
distribution of changed regions relative to the cursor and the active
window.

Typical usage::

    from ciu_agent.config.settings import get_default_settings
    from ciu_agent.core.state_classifier import StateClassifier

    settings = get_default_settings()
    classifier = StateClassifier(settings)

    classification = classifier.classify(
        diff=diff_result,
        cursor_pos=(cx, cy),
        active_window=window_info,
    )
    if classification.tier == 2:
        # send frame to Claude API for full canvas rebuild
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ciu_agent.config.settings import Settings
from ciu_agent.core.capture_engine import DiffResult
from ciu_agent.platform.interface import WindowInfo

# Maximum area (in pixels) for a changed region to be considered
# "small" — suitable for cursor-only, hover, or tooltip effects.
_SMALL_REGION_AREA: int = 2_500

# Maximum area (in pixels) for a "medium" region — menus, content
# updates, or compact dialogs.
_MEDIUM_REGION_AREA: int = 50_000

# Fraction of total screen area below which a change cluster is
# considered "localized" rather than "scattered".
_LOCALIZED_AREA_FRACTION: float = 0.10

# How close a region's centre must be to the screen centre (as a
# fraction of the screen diagonal) to be considered "centred".
_CENTRE_PROXIMITY_FRACTION: float = 0.15

# Minimum aspect ratio (height / width) for a region to look like
# a vertical menu dropdown.
_MENU_MIN_ASPECT_RATIO: float = 1.5


class ChangeType(Enum):
    """Classification of a detected screen change."""

    NO_CHANGE = "no_change"
    CURSOR_ONLY = "cursor_only"
    HOVER_EFFECT = "hover_effect"
    TOOLTIP = "tooltip"
    MENU_OPENED = "menu_opened"
    CONTENT_UPDATE = "content_update"
    DIALOG_APPEARED = "dialog_appeared"
    PAGE_NAVIGATION = "page_navigation"
    APP_SWITCH = "app_switch"


@dataclass
class ChangeClassification:
    """Result of classifying a screen change.

    Attributes:
        change_type: The high-level kind of change detected.
        tier: Recommended analysis tier (0, 1, or 2).
        regions: Bounding boxes ``(x, y, w, h)`` of regions
            that downstream tiers should analyse.
        confidence: Classifier confidence in ``[0.0, 1.0]``.
        should_wait: ``True`` when an animation may still be in
            progress and the caller should delay further analysis.
        wait_ms: Suggested delay in milliseconds before the next
            analysis pass, allowing animations to settle.
    """

    change_type: ChangeType
    tier: int
    regions: list[tuple[int, int, int, int]] = field(
        default_factory=list,
    )
    confidence: float = 1.0
    should_wait: bool = False
    wait_ms: int = 0


class StateClassifier:
    """Classifies screen changes and routes to the correct analysis tier.

    Applies heuristics from the architecture spec to determine what kind
    of change occurred and which tier should handle it.

    The classifier is stateful: it remembers the last active window title
    so it can detect application switches across successive calls.

    Args:
        settings: Immutable configuration supplying diff thresholds
            and stability-wait timing.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with injected settings.

        Args:
            settings: Configuration object providing
                ``diff_threshold_percent``,
                ``tier2_threshold_percent``, and
                ``stability_wait_ms``.
        """
        self._settings = settings
        self._last_active_window: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(
        self,
        diff: DiffResult,
        cursor_pos: tuple[int, int],
        active_window: WindowInfo | None = None,
    ) -> ChangeClassification:
        """Classify a screen change based on diff result and context.

        Decision order (first match wins):

        1. ``changed_percent < diff_threshold`` -> ``NO_CHANGE``, tier 0
        2. Active window changed                -> ``APP_SWITCH``, tier 2
        3. All changes near cursor and small    -> ``CURSOR_ONLY``, tier 0
        4. ``changed_percent >= tier2_threshold``-> ``PAGE_NAVIGATION``, tier 2
        5. Region-pattern heuristics             -> tier 1

        Args:
            diff: The Tier 0 diff result from ``CaptureEngine``.
            cursor_pos: Current cursor position ``(x, y)`` in logical
                pixels.
            active_window: Information about the currently focused
                window.  Used for app-switch detection.  May be
                ``None`` when unavailable.

        Returns:
            A ``ChangeClassification`` with tier recommendation and
            the regions downstream tiers should examine.
        """
        # 1. Below Tier 0 noise floor — nothing changed.
        if diff.changed_percent < self._settings.diff_threshold_percent:
            return ChangeClassification(
                change_type=ChangeType.NO_CHANGE,
                tier=0,
                regions=[],
                confidence=1.0,
                should_wait=False,
                wait_ms=0,
            )

        # 2. Application switch — full Tier 2 rebuild.
        if self._check_app_switch(active_window):
            should_wait, wait_ms = self._estimate_stability_wait(
                ChangeType.APP_SWITCH,
            )
            return ChangeClassification(
                change_type=ChangeType.APP_SWITCH,
                tier=2,
                regions=list(diff.changed_regions),
                confidence=0.95,
                should_wait=should_wait,
                wait_ms=wait_ms,
            )

        # 3. Cursor-only movement — tiny changes near cursor.
        if self._is_cursor_only(diff, cursor_pos):
            return ChangeClassification(
                change_type=ChangeType.CURSOR_ONLY,
                tier=0,
                regions=list(diff.changed_regions),
                confidence=0.9,
                should_wait=False,
                wait_ms=0,
            )

        # 4. Massive change — treat as page navigation.
        if (
            diff.changed_percent
            >= self._settings.tier2_threshold_percent
        ):
            should_wait, wait_ms = self._estimate_stability_wait(
                ChangeType.PAGE_NAVIGATION,
            )
            return ChangeClassification(
                change_type=ChangeType.PAGE_NAVIGATION,
                tier=2,
                regions=list(diff.changed_regions),
                confidence=0.85,
                should_wait=should_wait,
                wait_ms=wait_ms,
            )

        # 5. Moderate change — classify by region pattern (tier 1).
        change_type = self._classify_by_region_pattern(
            diff, cursor_pos,
        )
        should_wait, wait_ms = self._estimate_stability_wait(
            change_type,
        )

        # Dialogs may warrant tier 2 on the dialog region only.
        tier = 2 if change_type == ChangeType.DIALOG_APPEARED else 1

        return ChangeClassification(
            change_type=change_type,
            tier=tier,
            regions=list(diff.changed_regions),
            confidence=0.7,
            should_wait=should_wait,
            wait_ms=wait_ms,
        )

    # ------------------------------------------------------------------
    # App-switch detection
    # ------------------------------------------------------------------

    def _check_app_switch(
        self,
        active_window: WindowInfo | None,
    ) -> bool:
        """Check if the active application changed since the last call.

        The first call with a non-``None`` window always returns
        ``False`` (baseline establishment).

        Args:
            active_window: The currently focused window, or ``None``
                if the information is unavailable.

        Returns:
            ``True`` when the window title differs from the
            previously recorded title.
        """
        if active_window is None:
            return False

        current_title = active_window.title
        previous_title = self._last_active_window
        self._last_active_window = current_title

        # First observation — set baseline, do not flag as switch.
        if previous_title == "":
            return False

        return current_title != previous_title

    # ------------------------------------------------------------------
    # Cursor-only detection
    # ------------------------------------------------------------------

    def _is_cursor_only(
        self,
        diff: DiffResult,
        cursor_pos: tuple[int, int],
    ) -> bool:
        """Check if the change is only cursor movement.

        Cursor-only changes produce a small number of small changed
        regions that are all close to the cursor position.

        Args:
            diff: The frame diff result.
            cursor_pos: Current cursor ``(x, y)``.

        Returns:
            ``True`` when all changed regions are small and near
            the cursor.
        """
        if not diff.changed_regions:
            return False

        for region in diff.changed_regions:
            x, y, w, h = region
            area = w * h
            if area > _SMALL_REGION_AREA:
                return False
            if not self._is_near_cursor(region, cursor_pos):
                return False

        return True

    def _is_near_cursor(
        self,
        region: tuple[int, int, int, int],
        cursor_pos: tuple[int, int],
        margin: int = 50,
    ) -> bool:
        """Check if a region is near the cursor position.

        A region is considered near the cursor when the cursor lies
        within the region inflated by *margin* pixels on every side.

        Args:
            region: Bounding box ``(x, y, w, h)``.
            cursor_pos: Cursor position ``(cx, cy)``.
            margin: Pixel margin added around the region before the
                proximity test.

        Returns:
            ``True`` when the cursor is within the inflated region.
        """
        rx, ry, rw, rh = region
        cx, cy = cursor_pos

        return (
            rx - margin <= cx <= rx + rw + margin
            and ry - margin <= cy <= ry + rh + margin
        )

    # ------------------------------------------------------------------
    # Region-pattern classification
    # ------------------------------------------------------------------

    def _classify_by_region_pattern(
        self,
        diff: DiffResult,
        cursor_pos: tuple[int, int],
    ) -> ChangeType:
        """Classify a moderate change by the pattern of changed regions.

        Heuristics (evaluated in order):

        * Small region near cursor -> ``HOVER_EFFECT`` or ``TOOLTIP``
        * Tall narrow region near cursor -> ``MENU_OPENED``
        * Region near screen centre -> ``DIALOG_APPEARED``
        * Single compact region -> ``CONTENT_UPDATE``
        * Multiple scattered regions -> ``PAGE_NAVIGATION``

        Args:
            diff: The frame diff result with changed regions.
            cursor_pos: Current cursor ``(x, y)``.

        Returns:
            The best-matching ``ChangeType``.
        """
        regions = diff.changed_regions
        if not regions:
            return ChangeType.CONTENT_UPDATE

        # Aggregate bounding-box metrics.
        total_area = sum(w * h for _, _, w, h in regions)
        all_near_cursor = all(
            self._is_near_cursor(r, cursor_pos) for r in regions
        )

        # --- Small near-cursor changes: hover or tooltip -----------
        if all_near_cursor and total_area <= _SMALL_REGION_AREA:
            # Tooltip heuristic: a single new rectangular region
            # that was not there before.  We approximate by checking
            # whether there is exactly one region.
            if len(regions) == 1:
                return ChangeType.TOOLTIP
            return ChangeType.HOVER_EFFECT

        # --- Tall, narrow region near cursor: menu dropdown --------
        for region in regions:
            _, _, rw, rh = region
            area = rw * rh
            if (
                area <= _MEDIUM_REGION_AREA
                and rw > 0
                and rh / rw >= _MENU_MIN_ASPECT_RATIO
                and self._is_near_cursor(
                    region, cursor_pos, margin=100,
                )
            ):
                return ChangeType.MENU_OPENED

        # --- Centred moderate region: dialog / modal ---------------
        if self._has_centred_region(regions, diff):
            return ChangeType.DIALOG_APPEARED

        # --- Single compact region: content update -----------------
        if len(regions) <= 3 and total_area <= _MEDIUM_REGION_AREA:
            return ChangeType.CONTENT_UPDATE

        # --- Fallback: many or large scattered changes -------------
        return ChangeType.PAGE_NAVIGATION

    def _has_centred_region(
        self,
        regions: list[tuple[int, int, int, int]],
        diff: DiffResult,
    ) -> bool:
        """Check if any region is roughly centred on the screen.

        Uses the union bounding box of all regions to estimate the
        screen dimensions (this avoids coupling to the platform layer
        for screen-size queries).  A region is "centred" when its
        centre is within ``_CENTRE_PROXIMITY_FRACTION`` of the
        estimated screen diagonal from the estimated screen centre.

        Args:
            regions: Changed-region bounding boxes.
            diff: The diff result (used alongside *regions* for
                screen-extent estimation).

        Returns:
            ``True`` if at least one medium-or-larger region is near
            the screen centre.
        """
        if not regions:
            return False

        # Estimate screen extent from the union of all regions.
        max_x = max(x + w for x, y, w, h in regions)
        max_y = max(y + h for x, y, w, h in regions)

        # Guard against degenerate case.
        if max_x == 0 or max_y == 0:
            return False

        screen_cx = max_x / 2.0
        screen_cy = max_y / 2.0
        diag = (max_x ** 2 + max_y ** 2) ** 0.5
        threshold = diag * _CENTRE_PROXIMITY_FRACTION

        for rx, ry, rw, rh in regions:
            area = rw * rh
            if area < _SMALL_REGION_AREA:
                continue
            region_cx = rx + rw / 2.0
            region_cy = ry + rh / 2.0
            dist = (
                (region_cx - screen_cx) ** 2
                + (region_cy - screen_cy) ** 2
            ) ** 0.5
            if dist <= threshold:
                return True

        return False

    # ------------------------------------------------------------------
    # Stability wait estimation
    # ------------------------------------------------------------------

    def _estimate_stability_wait(
        self,
        change_type: ChangeType,
    ) -> tuple[bool, int]:
        """Determine whether to wait for animation stability.

        Fast UI transitions (CSS animations, menu slide-ins, dialog
        fade-ins) can cause transient diff spikes.  Waiting a short
        time before committing to analysis avoids wasting compute on
        intermediate frames.

        Args:
            change_type: The classified change type.

        Returns:
            A ``(should_wait, wait_ms)`` tuple.

            * ``NO_CHANGE``, ``CURSOR_ONLY``: no wait.
            * ``HOVER_EFFECT``, ``TOOLTIP``: 100 ms.
            * ``MENU_OPENED``, ``CONTENT_UPDATE``: 300 ms.
            * ``DIALOG_APPEARED``, ``PAGE_NAVIGATION``,
              ``APP_SWITCH``: full ``stability_wait_ms`` from
              settings.
        """
        no_wait: tuple[bool, int] = (False, 0)
        short_wait: tuple[bool, int] = (True, 100)
        medium_wait: tuple[bool, int] = (True, 300)
        full_wait: tuple[bool, int] = (
            True,
            self._settings.stability_wait_ms,
        )

        wait_map: dict[ChangeType, tuple[bool, int]] = {
            ChangeType.NO_CHANGE: no_wait,
            ChangeType.CURSOR_ONLY: no_wait,
            ChangeType.HOVER_EFFECT: short_wait,
            ChangeType.TOOLTIP: short_wait,
            ChangeType.MENU_OPENED: medium_wait,
            ChangeType.CONTENT_UPDATE: medium_wait,
            ChangeType.DIALOG_APPEARED: full_wait,
            ChangeType.PAGE_NAVIGATION: full_wait,
            ChangeType.APP_SWITCH: full_wait,
        }

        return wait_map.get(change_type, full_wait)
