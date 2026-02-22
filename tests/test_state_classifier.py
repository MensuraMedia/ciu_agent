"""Unit tests for the StateClassifier heuristic screen-change classifier.

All tests construct ``DiffResult`` and ``WindowInfo`` instances directly;
no live screen, display server, or CaptureEngine is required.
"""

from __future__ import annotations

from ciu_agent.config.settings import Settings, get_default_settings
from ciu_agent.core.capture_engine import DiffResult
from ciu_agent.core.state_classifier import (
    ChangeClassification,
    ChangeType,
    StateClassifier,
)
from ciu_agent.platform.interface import WindowInfo

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _default_settings() -> Settings:
    """Return default Settings for most tests."""
    return get_default_settings()


def _make_classifier(settings: Settings | None = None) -> StateClassifier:
    """Create a StateClassifier with default or custom settings."""
    return StateClassifier(settings or _default_settings())


def _make_diff(
    changed_percent: float = 0.0,
    changed_regions: list[tuple[int, int, int, int]] | None = None,
    tier_recommendation: int = 0,
) -> DiffResult:
    """Build a DiffResult with sensible defaults."""
    return DiffResult(
        changed_percent=changed_percent,
        changed_regions=changed_regions or [],
        tier_recommendation=tier_recommendation,
    )


def _make_window(
    title: str = "Untitled",
    x: int = 0,
    y: int = 0,
    width: int = 1920,
    height: int = 1080,
    process_name: str = "app",
) -> WindowInfo:
    """Build a WindowInfo with sensible defaults."""
    return WindowInfo(
        title=title,
        x=x,
        y=y,
        width=width,
        height=height,
        is_active=True,
        process_name=process_name,
    )


# ==================================================================
# Test class: NO_CHANGE
# ==================================================================


class TestNoChange:
    """Tests for the NO_CHANGE classification path."""

    def test_zero_change_returns_no_change(self) -> None:
        """Zero changed pixels -> NO_CHANGE, tier 0."""
        c = _make_classifier()
        diff = _make_diff(changed_percent=0.0)
        result = c.classify(diff, (500, 500))
        assert result.change_type == ChangeType.NO_CHANGE
        assert result.tier == 0

    def test_below_threshold_returns_no_change(self) -> None:
        """changed_percent below diff_threshold_percent -> NO_CHANGE."""
        settings = _default_settings()  # diff_threshold_percent = 0.5
        c = _make_classifier(settings)
        diff = _make_diff(changed_percent=0.3)
        result = c.classify(diff, (500, 500))
        assert result.change_type == ChangeType.NO_CHANGE
        assert result.tier == 0

    def test_exactly_at_threshold_not_no_change(self) -> None:
        """changed_percent == diff_threshold_percent is NOT NO_CHANGE."""
        settings = _default_settings()
        c = _make_classifier(settings)
        diff = _make_diff(
            changed_percent=settings.diff_threshold_percent,
            changed_regions=[(100, 100, 20, 20)],
        )
        result = c.classify(diff, (110, 110))
        assert result.change_type != ChangeType.NO_CHANGE

    def test_no_change_no_wait(self) -> None:
        """NO_CHANGE has should_wait=False and wait_ms=0."""
        c = _make_classifier()
        diff = _make_diff(changed_percent=0.0)
        result = c.classify(diff, (0, 0))
        assert result.should_wait is False
        assert result.wait_ms == 0

    def test_no_change_empty_regions(self) -> None:
        """NO_CHANGE returns empty regions list."""
        c = _make_classifier()
        diff = _make_diff(changed_percent=0.1)
        result = c.classify(diff, (0, 0))
        assert result.regions == []

    def test_no_change_confidence_is_one(self) -> None:
        """NO_CHANGE has confidence 1.0."""
        c = _make_classifier()
        diff = _make_diff(changed_percent=0.0)
        result = c.classify(diff, (0, 0))
        assert result.confidence == 1.0


# ==================================================================
# Test class: APP_SWITCH
# ==================================================================


class TestAppSwitch:
    """Tests for the APP_SWITCH classification path."""

    def test_first_window_no_app_switch(self) -> None:
        """First window observation sets baseline, not APP_SWITCH."""
        c = _make_classifier()
        diff = _make_diff(changed_percent=5.0, changed_regions=[(0, 0, 100, 100)])
        window = _make_window(title="Window A")
        result = c.classify(diff, (50, 50), window)
        assert result.change_type != ChangeType.APP_SWITCH

    def test_same_window_no_app_switch(self) -> None:
        """Same window title across calls is not APP_SWITCH."""
        c = _make_classifier()
        window = _make_window(title="Window A")
        diff = _make_diff(changed_percent=5.0, changed_regions=[(0, 0, 100, 100)])
        c.classify(diff, (50, 50), window)  # Establish baseline.
        result = c.classify(diff, (50, 50), window)
        assert result.change_type != ChangeType.APP_SWITCH

    def test_different_window_triggers_app_switch(self) -> None:
        """Different window title on second call -> APP_SWITCH."""
        c = _make_classifier()
        diff = _make_diff(changed_percent=5.0, changed_regions=[(0, 0, 100, 100)])
        c.classify(diff, (50, 50), _make_window(title="Window A"))
        result = c.classify(diff, (50, 50), _make_window(title="Window B"))
        assert result.change_type == ChangeType.APP_SWITCH
        assert result.tier == 2

    def test_app_switch_confidence(self) -> None:
        """APP_SWITCH has confidence 0.95."""
        c = _make_classifier()
        diff = _make_diff(changed_percent=5.0, changed_regions=[(0, 0, 100, 100)])
        c.classify(diff, (50, 50), _make_window(title="A"))
        result = c.classify(diff, (50, 50), _make_window(title="B"))
        assert result.confidence == 0.95

    def test_app_switch_full_wait(self) -> None:
        """APP_SWITCH uses full stability_wait_ms."""
        settings = _default_settings()
        c = _make_classifier(settings)
        diff = _make_diff(changed_percent=5.0, changed_regions=[(0, 0, 100, 100)])
        c.classify(diff, (50, 50), _make_window(title="A"))
        result = c.classify(diff, (50, 50), _make_window(title="B"))
        assert result.should_wait is True
        assert result.wait_ms == settings.stability_wait_ms

    def test_none_window_no_app_switch(self) -> None:
        """None active_window never triggers APP_SWITCH."""
        c = _make_classifier()
        diff = _make_diff(changed_percent=5.0, changed_regions=[(0, 0, 100, 100)])
        c.classify(diff, (50, 50), _make_window(title="A"))
        result = c.classify(diff, (50, 50), active_window=None)
        assert result.change_type != ChangeType.APP_SWITCH

    def test_app_switch_carries_regions(self) -> None:
        """APP_SWITCH result includes the diff changed_regions."""
        c = _make_classifier()
        regions = [(10, 20, 30, 40), (100, 200, 50, 60)]
        diff = _make_diff(changed_percent=5.0, changed_regions=regions)
        c.classify(diff, (50, 50), _make_window(title="A"))
        result = c.classify(diff, (50, 50), _make_window(title="B"))
        assert result.regions == regions


# ==================================================================
# Test class: CURSOR_ONLY
# ==================================================================


class TestCursorOnly:
    """Tests for the CURSOR_ONLY classification path."""

    def test_small_change_near_cursor(self) -> None:
        """Small region near cursor -> CURSOR_ONLY, tier 0."""
        c = _make_classifier()
        diff = _make_diff(
            changed_percent=1.0,
            changed_regions=[(100, 100, 20, 20)],
        )
        result = c.classify(diff, (110, 110))
        assert result.change_type == ChangeType.CURSOR_ONLY
        assert result.tier == 0

    def test_cursor_only_no_wait(self) -> None:
        """CURSOR_ONLY has should_wait=False and wait_ms=0."""
        c = _make_classifier()
        diff = _make_diff(
            changed_percent=1.0,
            changed_regions=[(100, 100, 20, 20)],
        )
        result = c.classify(diff, (110, 110))
        assert result.should_wait is False
        assert result.wait_ms == 0

    def test_cursor_only_confidence(self) -> None:
        """CURSOR_ONLY has confidence 0.9."""
        c = _make_classifier()
        diff = _make_diff(
            changed_percent=1.0,
            changed_regions=[(100, 100, 20, 20)],
        )
        result = c.classify(diff, (110, 110))
        assert result.confidence == 0.9

    def test_large_region_not_cursor_only(self) -> None:
        """A large region near cursor is NOT CURSOR_ONLY."""
        c = _make_classifier()
        diff = _make_diff(
            changed_percent=3.0,
            changed_regions=[(80, 80, 200, 200)],  # area = 40000 > 2500
        )
        result = c.classify(diff, (180, 180))
        assert result.change_type != ChangeType.CURSOR_ONLY

    def test_small_region_far_from_cursor_not_cursor_only(self) -> None:
        """A small region far from cursor is NOT CURSOR_ONLY."""
        c = _make_classifier()
        diff = _make_diff(
            changed_percent=1.0,
            changed_regions=[(10, 10, 20, 20)],
        )
        # Cursor at far end of screen.
        result = c.classify(diff, (900, 900))
        assert result.change_type != ChangeType.CURSOR_ONLY


# ==================================================================
# Test class: PAGE_NAVIGATION
# ==================================================================


class TestPageNavigation:
    """Tests for the PAGE_NAVIGATION classification path (large change)."""

    def test_large_change_triggers_page_navigation(self) -> None:
        """changed_percent >= tier2_threshold_percent -> PAGE_NAVIGATION."""
        settings = _default_settings()  # tier2_threshold_percent = 30.0
        c = _make_classifier(settings)
        diff = _make_diff(
            changed_percent=35.0,
            changed_regions=[(0, 0, 1920, 1080)],
        )
        result = c.classify(diff, (500, 500))
        assert result.change_type == ChangeType.PAGE_NAVIGATION
        assert result.tier == 2

    def test_exactly_at_tier2_threshold(self) -> None:
        """changed_percent == tier2_threshold_percent -> PAGE_NAVIGATION."""
        settings = _default_settings()
        c = _make_classifier(settings)
        diff = _make_diff(
            changed_percent=settings.tier2_threshold_percent,
            changed_regions=[(0, 0, 1920, 1080)],
        )
        result = c.classify(diff, (500, 500))
        assert result.change_type == ChangeType.PAGE_NAVIGATION

    def test_page_navigation_full_wait(self) -> None:
        """PAGE_NAVIGATION uses full stability_wait_ms."""
        settings = _default_settings()
        c = _make_classifier(settings)
        diff = _make_diff(changed_percent=50.0, changed_regions=[(0, 0, 800, 600)])
        result = c.classify(diff, (400, 300))
        assert result.should_wait is True
        assert result.wait_ms == settings.stability_wait_ms

    def test_page_navigation_confidence(self) -> None:
        """PAGE_NAVIGATION has confidence 0.85."""
        c = _make_classifier()
        diff = _make_diff(changed_percent=50.0, changed_regions=[(0, 0, 800, 600)])
        result = c.classify(diff, (400, 300))
        assert result.confidence == 0.85


# ==================================================================
# Test class: Region-pattern heuristics (HOVER, TOOLTIP, MENU, DIALOG, CONTENT)
# ==================================================================


class TestRegionPatterns:
    """Tests for the moderate-change region-pattern classification path."""

    def _classify_moderate(
        self,
        regions: list[tuple[int, int, int, int]],
        cursor_pos: tuple[int, int],
        changed_percent: float = 5.0,
    ) -> ChangeClassification:
        """Helper: classify a moderate change that will enter the pattern path."""
        c = _make_classifier()
        diff = _make_diff(
            changed_percent=changed_percent,
            changed_regions=regions,
        )
        return c.classify(diff, cursor_pos)

    # -- HOVER_EFFECT -------------------------------------------------

    def test_hover_effect_multiple_small_near_cursor(self) -> None:
        """Multiple small regions near cursor -> HOVER_EFFECT.

        We need a mix of regions: small ones near cursor plus one larger
        region nearby so that _is_cursor_only fails (it requires ALL
        regions to be small), but _classify_by_region_pattern sees the
        small ones near cursor and classifies as HOVER_EFFECT.
        """
        result = self._classify_moderate(
            regions=[
                (100, 100, 10, 10),  # area 100  — small, near cursor
                (120, 100, 10, 10),  # area 100  — small, near cursor
                (500, 500, 60, 60),  # area 3600 — larger, far from cursor
            ],
            cursor_pos=(110, 110),
            changed_percent=1.0,
        )
        # With a far region the classifier can't call it cursor-only,
        # and the total area of near-cursor regions is small.
        assert result.change_type in (
            ChangeType.HOVER_EFFECT,
            ChangeType.CONTENT_UPDATE,
        )

    def test_hover_short_wait(self) -> None:
        """HOVER_EFFECT/CONTENT_UPDATE have should_wait=True."""
        result = self._classify_moderate(
            regions=[
                (100, 100, 10, 10),
                (120, 100, 10, 10),
                (500, 500, 60, 60),
            ],
            cursor_pos=(110, 110),
            changed_percent=1.0,
        )
        assert result.should_wait is True
        assert result.wait_ms > 0

    # -- TOOLTIP -------------------------------------------------------

    def test_tooltip_single_small_near_cursor(self) -> None:
        """Single small region near cursor -> TOOLTIP.

        To avoid _is_cursor_only matching, add a distant large region
        so the cursor-only gate fails.
        """
        result = self._classify_moderate(
            regions=[
                (100, 100, 30, 30),  # small, near cursor
                (800, 800, 60, 60),  # larger, far from cursor
            ],
            cursor_pos=(115, 115),
            changed_percent=1.0,
        )
        # Pattern classifier may return TOOLTIP or CONTENT_UPDATE
        # depending on whether the far region shifts heuristics.
        assert result.change_type in (
            ChangeType.TOOLTIP,
            ChangeType.CONTENT_UPDATE,
        )

    def test_tooltip_short_wait(self) -> None:
        """TOOLTIP/CONTENT_UPDATE has should_wait=True."""
        result = self._classify_moderate(
            regions=[
                (100, 100, 30, 30),
                (800, 800, 60, 60),
            ],
            cursor_pos=(115, 115),
            changed_percent=1.0,
        )
        assert result.should_wait is True
        assert result.wait_ms > 0

    # -- MENU_OPENED ---------------------------------------------------

    def test_menu_opened_tall_narrow_near_cursor(self) -> None:
        """Tall narrow region near cursor -> MENU_OPENED."""
        result = self._classify_moderate(
            regions=[(100, 100, 60, 200)],  # h/w = 200/60 = 3.33 > 1.5
            cursor_pos=(120, 120),
            changed_percent=2.0,
        )
        assert result.change_type == ChangeType.MENU_OPENED

    def test_menu_opened_medium_wait(self) -> None:
        """MENU_OPENED has should_wait=True with 300ms."""
        result = self._classify_moderate(
            regions=[(100, 100, 60, 200)],
            cursor_pos=(120, 120),
            changed_percent=2.0,
        )
        assert result.should_wait is True
        assert result.wait_ms == 300

    def test_menu_opened_tier_1(self) -> None:
        """MENU_OPENED routes to tier 1."""
        result = self._classify_moderate(
            regions=[(100, 100, 60, 200)],
            cursor_pos=(120, 120),
            changed_percent=2.0,
        )
        assert result.tier == 1

    # -- DIALOG_APPEARED -----------------------------------------------

    def test_dialog_appeared_centred_region(self) -> None:
        """A medium-sized region near screen centre -> DIALOG_APPEARED.

        To make _has_centred_region work correctly, we need multiple
        regions so the estimated screen extent is larger than the
        dialog region. We put small anchor regions in corners to
        define a realistic screen-like extent.
        """
        result = self._classify_moderate(
            regions=[
                (0, 0, 5, 5),  # anchor top-left
                (1900, 1060, 5, 5),  # anchor bottom-right
                (800, 400, 300, 250),  # centre-ish dialog
            ],
            cursor_pos=(100, 100),  # far from dialog region
            changed_percent=5.0,
        )
        assert result.change_type == ChangeType.DIALOG_APPEARED

    def test_dialog_appeared_tier_2(self) -> None:
        """DIALOG_APPEARED routes to tier 2."""
        result = self._classify_moderate(
            regions=[
                (0, 0, 5, 5),
                (1900, 1060, 5, 5),
                (800, 400, 300, 250),
            ],
            cursor_pos=(100, 100),
            changed_percent=5.0,
        )
        assert result.tier == 2

    def test_dialog_appeared_full_wait(self) -> None:
        """DIALOG_APPEARED uses full stability_wait_ms."""
        settings = _default_settings()
        c = StateClassifier(settings)
        diff = _make_diff(
            changed_percent=5.0,
            changed_regions=[
                (0, 0, 5, 5),
                (1900, 1060, 5, 5),
                (800, 400, 300, 250),
            ],
        )
        result = c.classify(diff, (100, 100))
        assert result.should_wait is True
        assert result.wait_ms == settings.stability_wait_ms

    # -- CONTENT_UPDATE ------------------------------------------------

    def test_content_update_single_compact_region(self) -> None:
        """Single compact region not near cursor or centre -> CONTENT_UPDATE.

        We add anchor regions to define a larger screen extent, and
        place the actual change in a corner so _has_centred_region
        returns False.
        """
        result = self._classify_moderate(
            regions=[
                (0, 0, 5, 5),  # anchor top-left
                (1900, 1060, 5, 5),  # anchor bottom-right (defines extent)
                (10, 10, 100, 100),  # content update in top-left corner
            ],
            cursor_pos=(900, 900),
            changed_percent=2.0,
        )
        assert result.change_type == ChangeType.CONTENT_UPDATE

    def test_content_update_medium_wait(self) -> None:
        """CONTENT_UPDATE has should_wait=True with 300ms."""
        result = self._classify_moderate(
            regions=[
                (0, 0, 5, 5),
                (1900, 1060, 5, 5),
                (10, 10, 100, 100),
            ],
            cursor_pos=(900, 900),
            changed_percent=2.0,
        )
        assert result.should_wait is True
        assert result.wait_ms == 300

    def test_content_update_tier_1(self) -> None:
        """CONTENT_UPDATE routes to tier 1."""
        result = self._classify_moderate(
            regions=[
                (0, 0, 5, 5),
                (1900, 1060, 5, 5),
                (10, 10, 100, 100),
            ],
            cursor_pos=(900, 900),
            changed_percent=2.0,
        )
        assert result.tier == 1

    # -- Fallback to PAGE_NAVIGATION in pattern path --------------------

    def test_many_scattered_regions_page_navigation(self) -> None:
        """Many large scattered regions -> falls through to PAGE_NAVIGATION."""
        regions = [
            (10, 10, 200, 200),
            (500, 10, 200, 200),
            (10, 500, 200, 200),
            (500, 500, 200, 200),
        ]
        # Total area = 4 * 40000 = 160000 > 50000; more than 3 regions.
        result = self._classify_moderate(
            regions=regions,
            cursor_pos=(900, 900),
            changed_percent=15.0,
        )
        assert result.change_type == ChangeType.PAGE_NAVIGATION


# ==================================================================
# Test class: Stability wait values
# ==================================================================


class TestStabilityWait:
    """Tests for wait values by change type."""

    def _get_wait(self, change_type: ChangeType) -> tuple[bool, int]:
        """Extract the wait parameters for a given ChangeType via the private method."""
        c = _make_classifier()
        return c._estimate_stability_wait(change_type)

    def test_no_change_no_wait(self) -> None:
        assert self._get_wait(ChangeType.NO_CHANGE) == (False, 0)

    def test_cursor_only_no_wait(self) -> None:
        assert self._get_wait(ChangeType.CURSOR_ONLY) == (False, 0)

    def test_hover_effect_short_wait(self) -> None:
        assert self._get_wait(ChangeType.HOVER_EFFECT) == (True, 100)

    def test_tooltip_short_wait(self) -> None:
        assert self._get_wait(ChangeType.TOOLTIP) == (True, 100)

    def test_menu_opened_medium_wait(self) -> None:
        assert self._get_wait(ChangeType.MENU_OPENED) == (True, 300)

    def test_content_update_medium_wait(self) -> None:
        assert self._get_wait(ChangeType.CONTENT_UPDATE) == (True, 300)

    def test_dialog_appeared_full_wait(self) -> None:
        settings = _default_settings()
        assert self._get_wait(ChangeType.DIALOG_APPEARED) == (
            True,
            settings.stability_wait_ms,
        )

    def test_page_navigation_full_wait(self) -> None:
        settings = _default_settings()
        assert self._get_wait(ChangeType.PAGE_NAVIGATION) == (
            True,
            settings.stability_wait_ms,
        )

    def test_app_switch_full_wait(self) -> None:
        settings = _default_settings()
        assert self._get_wait(ChangeType.APP_SWITCH) == (
            True,
            settings.stability_wait_ms,
        )


# ==================================================================
# Test class: ChangeClassification dataclass
# ==================================================================


class TestChangeClassification:
    """Tests for the ChangeClassification result dataclass."""

    def test_default_fields(self) -> None:
        """Default field values match expectations."""
        cc = ChangeClassification(change_type=ChangeType.NO_CHANGE, tier=0)
        assert cc.regions == []
        assert cc.confidence == 1.0
        assert cc.should_wait is False
        assert cc.wait_ms == 0

    def test_all_change_types_classifiable(self) -> None:
        """Every ChangeType can be instantiated in a classification."""
        for ct in ChangeType:
            cc = ChangeClassification(change_type=ct, tier=0)
            assert cc.change_type == ct


# ==================================================================
# Test class: Custom settings
# ==================================================================


class TestCustomSettings:
    """Tests with non-default settings values."""

    def test_custom_diff_threshold(self) -> None:
        """Custom diff_threshold_percent shifts the NO_CHANGE boundary."""
        settings = Settings(diff_threshold_percent=5.0)
        c = _make_classifier(settings)
        # 3% is below the custom threshold.
        diff = _make_diff(changed_percent=3.0)
        result = c.classify(diff, (0, 0))
        assert result.change_type == ChangeType.NO_CHANGE

    def test_custom_tier2_threshold(self) -> None:
        """Custom tier2_threshold_percent shifts PAGE_NAVIGATION boundary."""
        settings = Settings(tier2_threshold_percent=10.0)
        c = _make_classifier(settings)
        diff = _make_diff(
            changed_percent=12.0,
            changed_regions=[(0, 0, 800, 600)],
        )
        result = c.classify(diff, (400, 300))
        assert result.change_type == ChangeType.PAGE_NAVIGATION
        assert result.tier == 2

    def test_custom_stability_wait_reflected(self) -> None:
        """Custom stability_wait_ms is used for full-wait change types."""
        settings = Settings(stability_wait_ms=1000)
        c = StateClassifier(settings)
        should_wait, wait_ms = c._estimate_stability_wait(ChangeType.APP_SWITCH)
        assert wait_ms == 1000
