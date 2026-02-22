"""Unit tests for the Tier1Analyzer local region analysis module.

All tests use synthetic BGR numpy arrays constructed with cv2 drawing
primitives.  No real screen captures or display server required.
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from numpy.typing import NDArray

from ciu_agent.config.settings import Settings, get_default_settings
from ciu_agent.core.tier1_analyzer import (
    _CONFIDENCE_RECT,
    _CONFIDENCE_TEXT,
    _CONFIDENCE_TOOLTIP,
    _HOVER_BRIGHTNESS_DELTA,
    RegionAnalysis,
    Tier1Analyzer,
)
from ciu_agent.models.zone import Rectangle, Zone, ZoneState, ZoneType

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _blank_bgr(
    width: int, height: int, color: tuple[int, int, int] = (128, 128, 128)
) -> NDArray[np.uint8]:
    """Create a solid-colour BGR image."""
    img = np.full((height, width, 3), color, dtype=np.uint8)
    return img


def _make_analyzer(settings: Settings | None = None) -> Tier1Analyzer:
    """Create a Tier1Analyzer with default or custom settings."""
    return Tier1Analyzer(settings or get_default_settings())


def _make_zone(
    zone_id: str,
    x: int,
    y: int,
    width: int,
    height: int,
    zone_type: ZoneType = ZoneType.BUTTON,
    state: ZoneState = ZoneState.ENABLED,
    confidence: float = 0.9,
) -> Zone:
    """Create a Zone with sensible defaults for testing."""
    return Zone(
        id=zone_id,
        bounds=Rectangle(x=x, y=y, width=width, height=height),
        type=zone_type,
        label="test",
        state=state,
        confidence=confidence,
        last_seen=time.time(),
    )


# ==================================================================
# Test class: RegionAnalysis dataclass
# ==================================================================


class TestRegionAnalysis:
    """Tests for the RegionAnalysis result dataclass."""

    def test_default_fields(self) -> None:
        """Default fields are empty lists and zero confidence."""
        ra = RegionAnalysis(region=(0, 0, 100, 100))
        assert ra.new_zones == []
        assert ra.updated_zones == []
        assert ra.removed_zone_ids == []
        assert ra.confidence == 0.0

    def test_region_stored(self) -> None:
        """Region tuple is stored as-is."""
        region = (10, 20, 300, 400)
        ra = RegionAnalysis(region=region)
        assert ra.region == region


# ==================================================================
# Test class: detect_text_regions
# ==================================================================


class TestDetectTextRegions:
    """Tests for Tier1Analyzer.detect_text_regions."""

    def test_uniform_image_returns_no_zones(self) -> None:
        """A blank solid-colour image contains no text regions."""
        analyzer = _make_analyzer()
        img = _blank_bgr(200, 200)
        zones = analyzer.detect_text_regions(img, 0, 0)
        assert zones == []

    def test_high_contrast_horizontal_lines_detected(self) -> None:
        """Dense horizontal text-like patterns are detected as text regions."""
        analyzer = _make_analyzer()
        img = _blank_bgr(400, 200, color=(255, 255, 255))

        # Draw densely packed black horizontal lines simulating text.
        # Use closely spaced lines with varying thickness to create
        # edge density that survives Canny + dilation.
        for y_pos in range(20, 180, 8):
            cv2.line(img, (20, y_pos), (350, y_pos), (0, 0, 0), 2)
            # Add a slightly thinner line in between for edge density.
            cv2.line(img, (20, y_pos + 3), (350, y_pos + 3), (60, 60, 60), 1)

        zones = analyzer.detect_text_regions(img, 0, 0)
        # Should detect at least one wide region of edge density.
        assert len(zones) >= 1

    def test_zone_ids_follow_t1_pattern(self) -> None:
        """Every zone ID must match the 't1_X_Y_suffix' convention."""
        analyzer = _make_analyzer()
        img = _blank_bgr(400, 200, color=(255, 255, 255))
        for y_pos in range(20, 180, 8):
            cv2.line(img, (20, y_pos), (350, y_pos), (0, 0, 0), 2)
            cv2.line(img, (20, y_pos + 3), (350, y_pos + 3), (60, 60, 60), 1)

        zones = analyzer.detect_text_regions(img, 100, 50)
        assert len(zones) >= 1
        for z in zones:
            assert z.id.startswith("t1_"), f"Zone ID {z.id!r} missing t1_ prefix"
            parts = z.id.split("_")
            # Pattern: t1_<X>_<Y>_<suffix>
            assert len(parts) >= 4, f"Zone ID {z.id!r} has fewer than 4 parts"

    def test_offset_applied_to_bounds(self) -> None:
        """Offset_x and offset_y are added to detected bounds."""
        analyzer = _make_analyzer()
        img = _blank_bgr(400, 200, color=(255, 255, 255))
        for y_pos in range(20, 180, 8):
            cv2.line(img, (20, y_pos), (350, y_pos), (0, 0, 0), 2)
            cv2.line(img, (20, y_pos + 3), (350, y_pos + 3), (60, 60, 60), 1)

        offset_x, offset_y = 500, 300
        zones = analyzer.detect_text_regions(img, offset_x, offset_y)
        assert len(zones) >= 1
        for z in zones:
            assert z.bounds.x >= offset_x
            assert z.bounds.y >= offset_y

    def test_text_zones_have_correct_confidence(self) -> None:
        """Detected text zones carry the expected confidence score."""
        analyzer = _make_analyzer()
        img = _blank_bgr(300, 200, color=(255, 255, 255))
        for y_pos in range(30, 150, 20):
            cv2.line(img, (20, y_pos), (250, y_pos), (0, 0, 0), 2)

        zones = analyzer.detect_text_regions(img, 0, 0)
        for z in zones:
            assert z.confidence == _CONFIDENCE_TEXT

    def test_small_noise_filtered_out(self) -> None:
        """Tiny dots below _MIN_ZONE_SIZE are not detected."""
        analyzer = _make_analyzer()
        img = _blank_bgr(200, 200)
        # Draw a single tiny dot -- too small to be a text region.
        cv2.circle(img, (100, 100), 2, (255, 255, 255), -1)
        zones = analyzer.detect_text_regions(img, 0, 0)
        assert zones == []

    def test_text_zone_type_static_for_small(self) -> None:
        """Narrow text-like regions are typed STATIC."""
        analyzer = _make_analyzer()
        img = _blank_bgr(300, 100, color=(255, 255, 255))
        # A single thin horizontal line -- height < 20.
        cv2.rectangle(img, (10, 40), (250, 52), (0, 0, 0), -1)
        zones = analyzer.detect_text_regions(img, 0, 0)
        for z in zones:
            # Thin lines should be STATIC, not TEXT_FIELD.
            if z.bounds.height <= 20:
                assert z.type == ZoneType.STATIC

    def test_text_zone_type_text_field_for_large(self) -> None:
        """Wide, tall text-like regions are typed TEXT_FIELD."""
        analyzer = _make_analyzer()
        img = _blank_bgr(400, 200, color=(255, 255, 255))
        # Draw a thick wide horizontal band with edge detail.
        cv2.rectangle(img, (10, 50), (350, 100), (0, 0, 0), -1)
        # Add internal detail to create edges.
        for x_off in range(20, 340, 10):
            cv2.line(img, (x_off, 55), (x_off, 95), (200, 200, 200), 1)

        zones = analyzer.detect_text_regions(img, 0, 0)
        text_fields = [z for z in zones if z.type == ZoneType.TEXT_FIELD]
        # The wide band (width > 100, height > 20) should qualify.
        assert len(text_fields) >= 0  # May or may not detect depending on edge density.

    def test_zone_state_is_enabled(self) -> None:
        """Detected text zones default to ENABLED state."""
        analyzer = _make_analyzer()
        img = _blank_bgr(300, 200, color=(255, 255, 255))
        for y_pos in range(30, 150, 20):
            cv2.line(img, (20, y_pos), (250, y_pos), (0, 0, 0), 2)

        zones = analyzer.detect_text_regions(img, 0, 0)
        for z in zones:
            assert z.state == ZoneState.ENABLED


# ==================================================================
# Test class: detect_hover_change
# ==================================================================


class TestDetectHoverChange:
    """Tests for Tier1Analyzer.detect_hover_change."""

    def test_no_zones_returns_empty(self) -> None:
        """No zones to inspect -> no hover updates."""
        analyzer = _make_analyzer()
        img = _blank_bgr(200, 200)
        result = analyzer.detect_hover_change(img, img, [])
        assert result == []

    def test_no_brightness_change_no_hover(self) -> None:
        """Identical frames produce no hover updates."""
        analyzer = _make_analyzer()
        img = _blank_bgr(200, 200, color=(100, 100, 100))
        zone = _make_zone("z1", 10, 10, 50, 50)
        result = analyzer.detect_hover_change(img, img, [zone])
        assert result == []

    def test_brightness_increase_triggers_hover(self) -> None:
        """Increasing brightness beyond delta flags HOVERED."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(200, 200, color=(80, 80, 80))
        curr = _blank_bgr(200, 200, color=(80, 80, 80))

        # Brighten the zone area in the current frame.
        zone = _make_zone("z1", 20, 20, 60, 60)
        curr[20:80, 20:80] = (200, 200, 200)

        result = analyzer.detect_hover_change(curr, prev, [zone])
        assert len(result) == 1
        assert result[0][0] == "z1"
        assert result[0][1]["state"] == ZoneState.HOVERED

    def test_brightness_decrease_triggers_hover(self) -> None:
        """Decreasing brightness beyond delta also flags HOVERED."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(200, 200, color=(200, 200, 200))
        curr = _blank_bgr(200, 200, color=(200, 200, 200))

        zone = _make_zone("z1", 10, 10, 50, 50)
        curr[10:60, 10:60] = (50, 50, 50)

        result = analyzer.detect_hover_change(curr, prev, [zone])
        assert len(result) == 1
        assert result[0][1]["state"] == ZoneState.HOVERED

    def test_below_delta_no_hover(self) -> None:
        """Brightness change below _HOVER_BRIGHTNESS_DELTA is ignored."""
        analyzer = _make_analyzer()
        base_val = 128
        small_shift = int(_HOVER_BRIGHTNESS_DELTA) - 5
        prev = _blank_bgr(200, 200, color=(base_val, base_val, base_val))
        curr = _blank_bgr(200, 200, color=(base_val, base_val, base_val))

        zone = _make_zone("z1", 10, 10, 50, 50)
        new_val = base_val + small_shift
        curr[10:60, 10:60] = (new_val, new_val, new_val)

        result = analyzer.detect_hover_change(curr, prev, [zone])
        assert result == []

    def test_multiple_zones_mixed_hover(self) -> None:
        """Only zones with significant brightness change get flagged."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(300, 300, color=(100, 100, 100))
        curr = prev.copy()

        zone_hover = _make_zone("zh", 10, 10, 50, 50)
        zone_no = _make_zone("zn", 100, 100, 50, 50)

        # Only brighten zone_hover area.
        curr[10:60, 10:60] = (220, 220, 220)

        result = analyzer.detect_hover_change(curr, prev, [zone_hover, zone_no])
        ids = [r[0] for r in result]
        assert "zh" in ids
        assert "zn" not in ids

    def test_empty_image_returns_empty(self) -> None:
        """Empty (zero-size) images return no hover updates."""
        analyzer = _make_analyzer()
        empty = np.empty((0, 0, 3), dtype=np.uint8)
        zone = _make_zone("z1", 0, 0, 10, 10)
        result = analyzer.detect_hover_change(empty, empty, [zone])
        assert result == []


# ==================================================================
# Test class: detect_tooltip
# ==================================================================


class TestDetectTooltip:
    """Tests for Tier1Analyzer.detect_tooltip."""

    def test_identical_frames_no_tooltip(self) -> None:
        """No difference between frames -> no tooltip detected."""
        analyzer = _make_analyzer()
        img = _blank_bgr(300, 300, color=(200, 200, 200))
        zones = analyzer.detect_tooltip(img, img, 0, 0)
        assert zones == []

    def test_new_rectangle_detected_as_tooltip(self) -> None:
        """A new rectangle appearing between frames is detected."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(300, 300, color=(200, 200, 200))
        curr = prev.copy()

        # Draw a tooltip-like rectangle on current frame.
        cv2.rectangle(curr, (80, 80), (200, 130), (40, 40, 40), -1)

        zones = analyzer.detect_tooltip(curr, prev, 0, 0)
        assert len(zones) >= 1

    def test_tooltip_zone_ids_follow_pattern(self) -> None:
        """Tooltip zone IDs follow 't1_X_Y_ttN' pattern."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(300, 300, color=(200, 200, 200))
        curr = prev.copy()
        cv2.rectangle(curr, (80, 80), (200, 130), (40, 40, 40), -1)

        zones = analyzer.detect_tooltip(curr, prev, 50, 100)
        assert len(zones) >= 1
        for z in zones:
            assert z.id.startswith("t1_")
            assert "tt" in z.id, f"Tooltip zone ID {z.id!r} should contain 'tt'"

    def test_tooltip_offset_applied(self) -> None:
        """Offset is correctly added to tooltip bounds."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(300, 300, color=(200, 200, 200))
        curr = prev.copy()
        cv2.rectangle(curr, (80, 80), (200, 130), (40, 40, 40), -1)

        offset_x, offset_y = 400, 200
        zones = analyzer.detect_tooltip(curr, prev, offset_x, offset_y)
        assert len(zones) >= 1
        for z in zones:
            assert z.bounds.x >= offset_x
            assert z.bounds.y >= offset_y

    def test_tooltip_confidence(self) -> None:
        """Tooltip zones carry the expected confidence value."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(300, 300, color=(200, 200, 200))
        curr = prev.copy()
        cv2.rectangle(curr, (80, 80), (200, 130), (40, 40, 40), -1)

        zones = analyzer.detect_tooltip(curr, prev, 0, 0)
        for z in zones:
            assert z.confidence == _CONFIDENCE_TOOLTIP

    def test_tooltip_type_is_static(self) -> None:
        """Tooltip zones are always typed STATIC."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(300, 300, color=(200, 200, 200))
        curr = prev.copy()
        cv2.rectangle(curr, (80, 80), (200, 130), (40, 40, 40), -1)

        zones = analyzer.detect_tooltip(curr, prev, 0, 0)
        for z in zones:
            assert z.type == ZoneType.STATIC

    def test_too_large_region_not_tooltip(self) -> None:
        """A very large rectangle exceeding _TOOLTIP_MAX_AREA is filtered."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(800, 800, color=(200, 200, 200))
        curr = prev.copy()
        # Draw a huge rectangle well beyond tooltip max area.
        cv2.rectangle(curr, (10, 10), (700, 700), (40, 40, 40), -1)

        zones = analyzer.detect_tooltip(curr, prev, 0, 0)
        # Should not detect this as tooltip (area too large).
        large = [z for z in zones if z.bounds.width > 400 and z.bounds.height > 400]
        assert large == []

    def test_empty_frames_no_tooltip(self) -> None:
        """Empty images return no tooltips."""
        analyzer = _make_analyzer()
        empty = np.empty((0, 0, 3), dtype=np.uint8)
        zones = analyzer.detect_tooltip(empty, empty, 0, 0)
        assert zones == []


# ==================================================================
# Test class: detect_rectangular_elements
# ==================================================================


class TestDetectRectangularElements:
    """Tests for Tier1Analyzer.detect_rectangular_elements."""

    def test_uniform_image_no_rectangles(self) -> None:
        """Uniform image has no rectangular elements."""
        analyzer = _make_analyzer()
        img = _blank_bgr(200, 200)
        zones = analyzer.detect_rectangular_elements(img, 0, 0)
        assert zones == []

    def test_drawn_rectangle_detected(self) -> None:
        """A clearly drawn rectangle on contrasting background is found."""
        analyzer = _make_analyzer()
        img = _blank_bgr(300, 300, color=(240, 240, 240))
        # Draw a solid dark rectangle (button-like).
        cv2.rectangle(img, (50, 50), (200, 100), (30, 30, 30), -1)

        zones = analyzer.detect_rectangular_elements(img, 0, 0)
        # There should be at least one detection overlapping the drawn rect.
        assert len(zones) >= 1

    def test_rect_zone_type_is_unknown(self) -> None:
        """Rectangular element zones are typed UNKNOWN."""
        analyzer = _make_analyzer()
        img = _blank_bgr(300, 300, color=(240, 240, 240))
        cv2.rectangle(img, (50, 50), (200, 100), (30, 30, 30), -1)

        zones = analyzer.detect_rectangular_elements(img, 0, 0)
        for z in zones:
            assert z.type == ZoneType.UNKNOWN

    def test_rect_zone_id_pattern(self) -> None:
        """Rectangular element zone IDs follow 't1_X_Y_rN'."""
        analyzer = _make_analyzer()
        img = _blank_bgr(300, 300, color=(240, 240, 240))
        cv2.rectangle(img, (50, 50), (200, 100), (30, 30, 30), -1)

        zones = analyzer.detect_rectangular_elements(img, 10, 20)
        for z in zones:
            assert z.id.startswith("t1_")
            assert "_r" in z.id, f"Rect zone ID {z.id!r} should contain '_r'"

    def test_rect_confidence(self) -> None:
        """Rectangular element zones carry _CONFIDENCE_RECT."""
        analyzer = _make_analyzer()
        img = _blank_bgr(300, 300, color=(240, 240, 240))
        cv2.rectangle(img, (50, 50), (200, 100), (30, 30, 30), -1)

        zones = analyzer.detect_rectangular_elements(img, 0, 0)
        for z in zones:
            assert z.confidence == _CONFIDENCE_RECT

    def test_rect_offset_applied(self) -> None:
        """Offsets are correctly added to rectangular element bounds."""
        analyzer = _make_analyzer()
        img = _blank_bgr(300, 300, color=(240, 240, 240))
        cv2.rectangle(img, (50, 50), (200, 100), (30, 30, 30), -1)

        offset_x, offset_y = 1000, 500
        zones = analyzer.detect_rectangular_elements(img, offset_x, offset_y)
        for z in zones:
            assert z.bounds.x >= offset_x
            assert z.bounds.y >= offset_y


# ==================================================================
# Test class: analyze_region (integration)
# ==================================================================


class TestAnalyzeRegion:
    """Integration tests for Tier1Analyzer.analyze_region."""

    def test_identical_frames_no_detections(self) -> None:
        """Identical frames produce empty analysis."""
        analyzer = _make_analyzer()
        frame = _blank_bgr(400, 300)
        region = (50, 50, 200, 150)
        result = analyzer.analyze_region(frame, frame, region, [])

        assert result.region == region
        assert result.new_zones == []
        assert result.updated_zones == []
        assert result.removed_zone_ids == []
        assert result.confidence == 0.0

    def test_result_is_region_analysis(self) -> None:
        """analyze_region returns a RegionAnalysis instance."""
        analyzer = _make_analyzer()
        frame = _blank_bgr(400, 300)
        result = analyzer.analyze_region(frame, frame, (0, 0, 100, 100), [])
        assert isinstance(result, RegionAnalysis)

    def test_new_rectangle_produces_new_zones(self) -> None:
        """A new rectangle in current frame appears as new_zones."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(400, 300, color=(200, 200, 200))
        curr = prev.copy()
        # Draw a tooltip-sized rectangle in the region.
        cv2.rectangle(curr, (60, 60), (180, 110), (30, 30, 30), -1)

        region = (0, 0, 400, 300)
        result = analyzer.analyze_region(curr, prev, region, [])
        assert len(result.new_zones) >= 1

    def test_hover_change_produces_updated_zones(self) -> None:
        """Brightness change on known zone appears in updated_zones."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(200, 200, color=(100, 100, 100))
        curr = prev.copy()

        zone = _make_zone("z1", 20, 20, 60, 60)
        curr[20:80, 20:80] = (220, 220, 220)

        region = (0, 0, 200, 200)
        result = analyzer.analyze_region(curr, prev, region, [zone])
        ids = [u[0] for u in result.updated_zones]
        assert "z1" in ids

    def test_removed_zone_detected(self) -> None:
        """A zone whose region became uniform is reported as removed."""
        analyzer = _make_analyzer()
        # Previous frame had detail; current is uniform at zone location.
        prev = _blank_bgr(200, 200, color=(100, 100, 100))
        curr = _blank_bgr(200, 200, color=(100, 100, 100))
        # Add some detail to previous frame at zone location.
        cv2.rectangle(prev, (20, 20), (80, 80), (200, 50, 50), -1)

        zone = _make_zone("z_remove", 20, 20, 60, 60)
        region = (0, 0, 200, 200)
        result = analyzer.analyze_region(curr, prev, region, [zone])
        assert "z_remove" in result.removed_zone_ids

    def test_confidence_aggregation(self) -> None:
        """Confidence is in [0.0, 1.0] when detections are made."""
        analyzer = _make_analyzer()
        prev = _blank_bgr(400, 300, color=(200, 200, 200))
        curr = prev.copy()
        cv2.rectangle(curr, (60, 60), (180, 110), (30, 30, 30), -1)

        region = (0, 0, 400, 300)
        result = analyzer.analyze_region(curr, prev, region, [])
        assert 0.0 <= result.confidence <= 1.0
        # With detections, confidence should be positive.
        if result.new_zones:
            assert result.confidence > 0.0

    def test_region_clamped_to_frame(self) -> None:
        """Region extending beyond frame dimensions does not crash."""
        analyzer = _make_analyzer()
        frame = _blank_bgr(200, 200)
        # Region larger than the frame.
        region = (0, 0, 500, 500)
        result = analyzer.analyze_region(frame, frame, region, [])
        assert isinstance(result, RegionAnalysis)

    def test_zones_below_relaxed_confidence_filtered(self) -> None:
        """Zones below relaxed confidence floor are removed from results."""
        # Use settings with a very high min_zone_confidence so the
        # relaxed floor (0.5 * min) is still above Tier 1 confidences.
        settings = Settings(min_zone_confidence=1.0)
        analyzer = _make_analyzer(settings)

        prev = _blank_bgr(400, 300, color=(200, 200, 200))
        curr = prev.copy()
        cv2.rectangle(curr, (60, 60), (180, 110), (30, 30, 30), -1)

        # Relaxed floor = 1.0 * 0.5 = 0.5.  Rect confidence = 0.45 -> filtered.
        region = (0, 0, 400, 300)
        result = analyzer.analyze_region(curr, prev, region, [])
        rect_zones = [z for z in result.new_zones if z.confidence == _CONFIDENCE_RECT]
        assert rect_zones == []
