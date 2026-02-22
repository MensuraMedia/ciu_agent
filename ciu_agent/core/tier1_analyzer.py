"""Tier 1 local region analysis using OpenCV for lightweight zone updates.

The ``Tier1Analyzer`` examines localised screen changes identified by
Tier 0 frame differencing and attempts to update the zone registry
without making any API calls.  It detects text regions, hover-state
changes, tooltips, and generic rectangular UI elements using pure
OpenCV operations that run entirely on CPU.

This module sits between Tier 0 (fast frame diff) and Tier 2 (full API
rebuild).  Its analyses carry moderate confidence (0.4--0.7) and are
designed to keep the canvas map reasonably fresh between expensive
Tier 2 refreshes.

Typical usage::

    from ciu_agent.config.settings import get_default_settings

    settings = get_default_settings()
    analyzer = Tier1Analyzer(settings)

    result = analyzer.analyze_region(
        current_frame, previous_frame, region, existing_zones,
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np
from numpy.typing import NDArray

from ciu_agent.config.settings import Settings
from ciu_agent.models.zone import Rectangle, Zone, ZoneState, ZoneType

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Minimum zone dimension in pixels.  Anything smaller is noise.
_MIN_ZONE_SIZE: int = 10

# Canny edge detection thresholds for text region detection.
_CANNY_LOW: int = 50
_CANNY_HIGH: int = 150

# Dilation kernel size for connecting nearby text edges.
_TEXT_DILATE_KERNEL: tuple[int, int] = (15, 3)

# Minimum aspect ratio (w/h) for a contour to qualify as a text line.
_TEXT_MIN_ASPECT: float = 1.5

# Pixel-intensity threshold for the absolute-diff mask used by
# tooltip and hover detectors.
_DIFF_INTENSITY_THRESHOLD: int = 30

# Mean brightness change (0--255) required to flag a hover effect.
_HOVER_BRIGHTNESS_DELTA: float = 15.0

# Maximum area (in pixels) for a contour to qualify as a tooltip.
_TOOLTIP_MAX_AREA: int = 80_000

# Minimum area (in pixels) for a contour to qualify as a tooltip.
_TOOLTIP_MIN_AREA: int = 200

# Minimum rectangularity ratio (contour area / bounding rect area).
# 1.0 = perfect rectangle.
_MIN_RECTANGULARITY: float = 0.6

# Vertex count bounds for approxPolyDP to qualify as rectangular.
_RECT_MIN_VERTICES: int = 4
_RECT_MAX_VERTICES: int = 6

# Adaptive threshold block size for rectangular element detection.
_ADAPTIVE_BLOCK_SIZE: int = 11

# Adaptive threshold C constant.
_ADAPTIVE_C: int = 2

# Standard-deviation ceiling for "uniform area" detection.  A zone
# whose pixel std-dev falls below this is considered removed.
_UNIFORM_STD_THRESHOLD: float = 5.0

# Confidence bands for Tier 1 detections.
_CONFIDENCE_TEXT: float = 0.55
_CONFIDENCE_HOVER: float = 0.60
_CONFIDENCE_TOOLTIP: float = 0.50
_CONFIDENCE_RECT: float = 0.45
_CONFIDENCE_REMOVED: float = 0.50


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class RegionAnalysis:
    """Result of Tier 1 local analysis on a screen region.

    Attributes:
        region: ``(x, y, w, h)`` bounding box that was analysed.
        new_zones: Newly detected zones in the region.
        updated_zones: ``(zone_id, changed_fields)`` pairs for zones
            whose state changed (e.g. hover effects).
        removed_zone_ids: IDs of zones that no longer appear in the
            region.
        confidence: Overall confidence of this analysis in [0.0, 1.0].
    """

    region: tuple[int, int, int, int]
    new_zones: list[Zone] = field(default_factory=list)
    updated_zones: list[tuple[str, dict]] = field(
        default_factory=list,
    )
    removed_zone_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class Tier1Analyzer:
    """Local region analysis using OpenCV for lightweight zone updates.

    This tier handles localised screen changes without calling the API:

    - **Text changes** -- new text appearing or disappearing.
    - **Hover effects** -- brightness / colour shifts on known zones.
    - **Tooltip detection** -- small rectangular pop-ups near the
      cursor.
    - **Menu / dropdown expansion** -- new rectangular regions below
      an existing zone.

    All processing runs on CPU using OpenCV, making the analyser
    suitable for Intel UHD-class hardware with no discrete GPU.

    Args:
        settings: Immutable configuration object that controls
            confidence thresholds and zone lifecycle.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with injected settings.

        Args:
            settings: Configuration governing minimum confidence
                and other detection parameters.
        """
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_region(
        self,
        current_frame: NDArray[np.uint8],
        previous_frame: NDArray[np.uint8],
        region: tuple[int, int, int, int],
        existing_zones: list[Zone],
    ) -> RegionAnalysis:
        """Analyze a changed region of the screen.

        Crops both frames to the target region and runs every
        detection method in sequence.  Results are aggregated into
        a single ``RegionAnalysis``.

        Args:
            current_frame: The current full screenshot (BGR).
            previous_frame: The previous full screenshot (BGR).
            region: ``(x, y, w, h)`` bounding box of the changed
                area.
            existing_zones: Currently registered zones for context.

        Returns:
            ``RegionAnalysis`` with detected changes.
        """
        rx, ry, rw, rh = region

        # 1. Crop both frames to the region.
        current_crop = self._crop(current_frame, rx, ry, rw, rh)
        previous_crop = self._crop(
            previous_frame,
            rx,
            ry,
            rw,
            rh,
        )

        # 2. Identify which existing zones overlap this region.
        region_rect = Rectangle(
            x=rx,
            y=ry,
            width=rw,
            height=rh,
        )
        zones_in_region = [z for z in existing_zones if z.bounds.overlaps(region_rect)]

        # 3. Run each detection method.
        new_zones: list[Zone] = []

        text_zones = self.detect_text_regions(
            current_crop,
            rx,
            ry,
        )
        new_zones.extend(text_zones)

        tooltip_zones = self.detect_tooltip(
            current_crop,
            previous_crop,
            rx,
            ry,
        )
        new_zones.extend(tooltip_zones)

        rect_zones = self.detect_rectangular_elements(
            current_crop,
            rx,
            ry,
        )
        new_zones.extend(rect_zones)

        hover_updates = self.detect_hover_change(
            current_crop,
            previous_crop,
            zones_in_region,
        )

        # 4. Detect removed zones: existing zones in the region
        #    whose bounding area is now uniform colour.
        removed_ids = self._detect_removed_zones(
            current_crop,
            zones_in_region,
            rx,
            ry,
        )

        # 5. Filter new zones below the relaxed confidence floor.
        #    Tier 1 confidence is intentionally lower than Tier 2,
        #    so we apply half the configured minimum.
        relaxed_conf = self._settings.min_zone_confidence * 0.5
        new_zones = [z for z in new_zones if z.confidence >= relaxed_conf]

        # 6. Compute aggregate confidence.
        confidence = self._aggregate_confidence(
            new_zones,
            hover_updates,
            removed_ids,
        )

        return RegionAnalysis(
            region=region,
            new_zones=new_zones,
            updated_zones=hover_updates,
            removed_zone_ids=removed_ids,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Detection: text regions
    # ------------------------------------------------------------------

    def detect_text_regions(
        self,
        region_image: NDArray[np.uint8],
        offset_x: int,
        offset_y: int,
    ) -> list[Zone]:
        """Detect text-containing regions via edge density analysis.

        Uses morphological operations to find areas with high edge
        density (characteristic of text).  Returns zones of type
        ``STATIC`` (display text) or ``TEXT_FIELD`` when the region
        is large enough to be an input area.

        Args:
            region_image: Cropped BGR image of the region.
            offset_x: X offset of the region in screen coordinates.
            offset_y: Y offset of the region in screen coordinates.

        Returns:
            A list of ``Zone`` objects representing detected text
            regions.
        """
        gray = cv2.cvtColor(region_image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, _CANNY_LOW, _CANNY_HIGH)

        # Dilate horizontally to merge characters into text lines.
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            _TEXT_DILATE_KERNEL,
        )
        dilated = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(
            dilated,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        zones: list[Zone] = []
        now = time.time()

        for idx, contour in enumerate(contours):
            bx, by, bw, bh = cv2.boundingRect(contour)

            # Filter noise: must meet minimum size.
            if bw < _MIN_ZONE_SIZE or bh < _MIN_ZONE_SIZE:
                continue

            # Text regions are typically wider than tall.
            aspect = bw / max(bh, 1)
            if aspect < _TEXT_MIN_ASPECT:
                continue

            # Large, wide regions may be text input fields.
            zone_type = ZoneType.TEXT_FIELD if bh > 20 and bw > 100 else ZoneType.STATIC

            zone_id = f"t1_{offset_x + bx}_{offset_y + by}_{idx}"
            zones.append(
                Zone(
                    id=zone_id,
                    bounds=Rectangle(
                        x=offset_x + bx,
                        y=offset_y + by,
                        width=bw,
                        height=bh,
                    ),
                    type=zone_type,
                    label="",
                    state=ZoneState.ENABLED,
                    confidence=_CONFIDENCE_TEXT,
                    last_seen=now,
                )
            )

        return zones

    # ------------------------------------------------------------------
    # Detection: hover changes
    # ------------------------------------------------------------------

    def detect_hover_change(
        self,
        current_region: NDArray[np.uint8],
        previous_region: NDArray[np.uint8],
        zones_in_region: list[Zone],
    ) -> list[tuple[str, dict]]:
        """Detect hover-state changes on existing zones.

        Compares mean brightness within known zone bounds between
        the two frames.  If a zone's appearance changed significantly
        it is flagged with ``ZoneState.HOVERED``.

        The method infers the screen-space origin of the region crop
        from the bounding boxes of the zones that overlap it.  For
        best accuracy, ``zones_in_region`` should contain only zones
        that genuinely overlap the analysed region (the caller in
        ``analyze_region`` guarantees this).

        Args:
            current_region: Cropped BGR image of the current region.
            previous_region: Cropped BGR image of the previous
                region.
            zones_in_region: Existing zones that overlap the
                analysed region.

        Returns:
            A list of ``(zone_id, {"state": ZoneState.HOVERED})``
            tuples for every zone whose appearance changed.
        """
        if not zones_in_region:
            return []
        if current_region.size == 0 or previous_region.size == 0:
            return []

        cur_gray = cv2.cvtColor(
            current_region,
            cv2.COLOR_BGR2GRAY,
        )
        prev_gray = cv2.cvtColor(
            previous_region,
            cv2.COLOR_BGR2GRAY,
        )

        rh, rw = cur_gray.shape[:2]

        # Infer the screen-space origin of the region crop.
        # The crop starts at (region_x, region_y) on screen.  We
        # reconstruct this by finding the minimum zone coordinate
        # among overlapping zones, which is an upper bound on the
        # region origin.  For zones that are fully contained in the
        # region this is exact.
        region_ox = min(z.bounds.x for z in zones_in_region)
        region_oy = min(z.bounds.y for z in zones_in_region)

        updates: list[tuple[str, dict]] = []

        for zone in zones_in_region:
            # Zone bounds in region-local coordinates.
            lx = zone.bounds.x - region_ox
            ly = zone.bounds.y - region_oy
            lx2 = lx + zone.bounds.width
            ly2 = ly + zone.bounds.height

            # Clamp to region image dimensions.
            lx = max(0, lx)
            ly = max(0, ly)
            lx2 = min(rw, lx2)
            ly2 = min(rh, ly2)

            if lx2 <= lx or ly2 <= ly:
                continue

            cur_patch = cur_gray[ly:ly2, lx:lx2]
            prev_patch = prev_gray[ly:ly2, lx:lx2]

            if cur_patch.size == 0 or prev_patch.size == 0:
                continue

            cur_mean = float(cv2.mean(cur_patch)[0])
            prev_mean = float(cv2.mean(prev_patch)[0])
            delta = abs(cur_mean - prev_mean)

            if delta >= _HOVER_BRIGHTNESS_DELTA:
                updates.append(
                    (
                        zone.id,
                        {"state": ZoneState.HOVERED},
                    )
                )

        return updates

    # ------------------------------------------------------------------
    # Detection: tooltips
    # ------------------------------------------------------------------

    def detect_tooltip(
        self,
        current_region: NDArray[np.uint8],
        previous_region: NDArray[np.uint8],
        offset_x: int,
        offset_y: int,
    ) -> list[Zone]:
        """Detect newly appeared tooltip-like elements.

        Tooltips are small, rectangular, high-contrast regions that
        appeared in the current frame but were absent in the previous
        one.

        Args:
            current_region: Cropped BGR image of the current region.
            previous_region: Cropped BGR image of the previous
                region.
            offset_x: X offset of the region in screen coordinates.
            offset_y: Y offset of the region in screen coordinates.

        Returns:
            ``Zone`` objects with type ``STATIC`` and state
            ``ENABLED``.
        """
        if current_region.size == 0 or previous_region.size == 0:
            return []

        cur_gray = cv2.cvtColor(
            current_region,
            cv2.COLOR_BGR2GRAY,
        )
        prev_gray = cv2.cvtColor(
            previous_region,
            cv2.COLOR_BGR2GRAY,
        )

        diff = cv2.absdiff(cur_gray, prev_gray)
        _, thresh = cv2.threshold(
            diff,
            _DIFF_INTENSITY_THRESHOLD,
            255,
            cv2.THRESH_BINARY,
        )

        # Clean up small specks with morphological opening.
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (5, 5),
        )
        cleaned = cv2.morphologyEx(
            thresh,
            cv2.MORPH_OPEN,
            kernel,
        )

        contours, _ = cv2.findContours(
            cleaned,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        zones: list[Zone] = []
        now = time.time()

        for idx, contour in enumerate(contours):
            bx, by, bw, bh = cv2.boundingRect(contour)

            # Filter by size.
            area = bw * bh
            if area < _TOOLTIP_MIN_AREA:
                continue
            if area > _TOOLTIP_MAX_AREA:
                continue
            if bw < _MIN_ZONE_SIZE or bh < _MIN_ZONE_SIZE:
                continue

            # Rectangularity: contour area vs bounding rect.
            contour_area = cv2.contourArea(contour)
            if contour_area < 1:
                continue
            rectangularity = contour_area / area
            if rectangularity < _MIN_RECTANGULARITY:
                continue

            zone_id = f"t1_{offset_x + bx}_{offset_y + by}_tt{idx}"
            zones.append(
                Zone(
                    id=zone_id,
                    bounds=Rectangle(
                        x=offset_x + bx,
                        y=offset_y + by,
                        width=bw,
                        height=bh,
                    ),
                    type=ZoneType.STATIC,
                    label="",
                    state=ZoneState.ENABLED,
                    confidence=_CONFIDENCE_TOOLTIP,
                    last_seen=now,
                )
            )

        return zones

    # ------------------------------------------------------------------
    # Detection: rectangular elements
    # ------------------------------------------------------------------

    def detect_rectangular_elements(
        self,
        region_image: NDArray[np.uint8],
        offset_x: int,
        offset_y: int,
    ) -> list[Zone]:
        """Detect rectangular UI elements (buttons, fields, etc.).

        Uses edge detection and contour analysis to find rectangular
        shapes that could be interactive elements.

        Args:
            region_image: Cropped BGR image of the region.
            offset_x: X offset of the region in screen coordinates.
            offset_y: Y offset of the region in screen coordinates.

        Returns:
            ``Zone`` objects with type ``UNKNOWN``.
        """
        gray = cv2.cvtColor(region_image, cv2.COLOR_BGR2GRAY)

        # Adaptive threshold handles varying background brightness.
        binary = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            _ADAPTIVE_BLOCK_SIZE,
            _ADAPTIVE_C,
        )

        # Close small gaps in element borders.
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (3, 3),
        )
        closed = cv2.morphologyEx(
            binary,
            cv2.MORPH_CLOSE,
            kernel,
        )

        contours, _ = cv2.findContours(
            closed,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        zones: list[Zone] = []
        now = time.time()

        for idx, contour in enumerate(contours):
            bx, by, bw, bh = cv2.boundingRect(contour)

            # Minimum size filter.
            if bw < _MIN_ZONE_SIZE or bh < _MIN_ZONE_SIZE:
                continue

            # Approximate the contour to a polygon.
            perimeter = cv2.arcLength(contour, closed=True)
            if perimeter < 1:
                continue
            approx = cv2.approxPolyDP(
                contour,
                0.02 * perimeter,
                closed=True,
            )
            vertex_count = len(approx)

            # Keep only roughly rectangular shapes.
            if not (_RECT_MIN_VERTICES <= vertex_count <= _RECT_MAX_VERTICES):
                continue

            # Rectangularity check.
            contour_area = cv2.contourArea(contour)
            bbox_area = bw * bh
            if bbox_area < 1:
                continue
            rectangularity = contour_area / bbox_area
            if rectangularity < _MIN_RECTANGULARITY:
                continue

            zone_id = f"t1_{offset_x + bx}_{offset_y + by}_r{idx}"
            zones.append(
                Zone(
                    id=zone_id,
                    bounds=Rectangle(
                        x=offset_x + bx,
                        y=offset_y + by,
                        width=bw,
                        height=bh,
                    ),
                    type=ZoneType.UNKNOWN,
                    label="",
                    state=ZoneState.ENABLED,
                    confidence=_CONFIDENCE_RECT,
                    last_seen=now,
                )
            )

        return zones

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _crop(
        frame: NDArray[np.uint8],
        x: int,
        y: int,
        w: int,
        h: int,
    ) -> NDArray[np.uint8]:
        """Crop a frame to the given bounding box.

        Coordinates are clamped to the frame dimensions to prevent
        out-of-bounds slicing.

        Args:
            frame: Full screenshot (BGR), shape ``(H, W, 3)``.
            x: Left edge of the crop.
            y: Top edge of the crop.
            w: Width of the crop.
            h: Height of the crop.

        Returns:
            The cropped sub-image as a contiguous NumPy array.
        """
        fh, fw = frame.shape[:2]
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(fw, x + w)
        y1 = min(fh, y + h)
        return np.ascontiguousarray(frame[y0:y1, x0:x1])

    def _detect_removed_zones(
        self,
        current_crop: NDArray[np.uint8],
        zones_in_region: list[Zone],
        region_x: int,
        region_y: int,
    ) -> list[str]:
        """Identify zones that no longer appear in the region.

        Checks whether the area of each existing zone in the current
        frame is now a uniform (flat) colour, suggesting the element
        has disappeared.

        Args:
            current_crop: Cropped BGR image of the current region.
            zones_in_region: Existing zones overlapping this region.
            region_x: Screen-space X origin of the region.
            region_y: Screen-space Y origin of the region.

        Returns:
            IDs of zones that appear to have been removed.
        """
        if not zones_in_region:
            return []

        gray = cv2.cvtColor(current_crop, cv2.COLOR_BGR2GRAY)
        rh, rw = gray.shape[:2]
        removed: list[str] = []

        for zone in zones_in_region:
            lx = zone.bounds.x - region_x
            ly = zone.bounds.y - region_y
            lx2 = lx + zone.bounds.width
            ly2 = ly + zone.bounds.height

            # Clamp to region image dimensions.
            lx = max(0, lx)
            ly = max(0, ly)
            lx2 = min(rw, lx2)
            ly2 = min(rh, ly2)

            if lx2 <= lx or ly2 <= ly:
                continue

            patch = gray[ly:ly2, lx:lx2]
            if patch.size == 0:
                continue

            # A zone is considered removed when its area is nearly
            # uniform (very low std-dev of pixel intensities).
            _, std_dev = cv2.meanStdDev(patch)
            if float(std_dev[0][0]) < _UNIFORM_STD_THRESHOLD:
                removed.append(zone.id)

        return removed

    @staticmethod
    def _aggregate_confidence(
        new_zones: list[Zone],
        hover_updates: list[tuple[str, dict]],
        removed_ids: list[str],
    ) -> float:
        """Compute an overall confidence score for the analysis.

        The score is the mean of individual detection confidences,
        clamped to [0.0, 1.0].  If no detections were made the
        confidence is 0.0.

        Args:
            new_zones: Newly detected zones.
            hover_updates: Hover-state change tuples.
            removed_ids: IDs of removed zones.

        Returns:
            Aggregate confidence in [0.0, 1.0].
        """
        scores: list[float] = [z.confidence for z in new_zones]
        scores.extend(_CONFIDENCE_HOVER for _ in hover_updates)
        scores.extend(_CONFIDENCE_REMOVED for _ in removed_ids)

        if not scores:
            return 0.0

        mean = sum(scores) / len(scores)
        return max(0.0, min(1.0, mean))
