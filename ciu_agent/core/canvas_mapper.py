"""Canvas Mapper: orchestrator that wires all analysis tiers and the zone registry.

The ``CanvasMapper`` is the central coordinator for Phase 2.  It receives
captured frames, routes them through the appropriate analysis tier using the
``StateClassifier``, and updates the ``ZoneRegistry`` with the results.

Architecture::

    CaptureEngine
        |
        v
    CanvasMapper.process_frame()
        |
        +-- StateClassifier.classify()   -->  tier 0 / 1 / 2
        |
        +-- Tier 0: no-op (diff already done)
        +-- Tier 1: Tier1Analyzer.analyze_region()
        +-- Tier 2: Tier2Analyzer.analyze[_sync]()
        |
        v
    ZoneRegistry (updated)

Each tier is injected as a dependency and can be swapped independently,
satisfying the project's modularity requirement.

Typical usage::

    from ciu_agent.config.settings import get_default_settings
    from ciu_agent.core.canvas_mapper import CanvasMapper
    from ciu_agent.core.zone_registry import ZoneRegistry
    from ciu_agent.core.state_classifier import StateClassifier
    from ciu_agent.core.tier1_analyzer import Tier1Analyzer
    from ciu_agent.core.tier2_analyzer import Tier2Analyzer

    settings = get_default_settings()
    mapper = CanvasMapper(
        settings=settings,
        registry=ZoneRegistry(),
        classifier=StateClassifier(settings),
        tier1=Tier1Analyzer(settings),
        tier2=Tier2Analyzer(settings, api_key="sk-ant-..."),
    )

    result = mapper.process_frame(
        current_frame=frame.image,
        previous_frame=prev.image,
        diff=diff_result,
        cursor_pos=(frame.cursor_x, frame.cursor_y),
        active_window=window_info,
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from ciu_agent.config.settings import Settings
from ciu_agent.core.capture_engine import DiffResult
from ciu_agent.core.state_classifier import (
    ChangeClassification,
    ChangeType,
    StateClassifier,
)
from ciu_agent.core.tier1_analyzer import RegionAnalysis, Tier1Analyzer
from ciu_agent.core.tier2_analyzer import (
    Tier2Analyzer,
    Tier2Request,
    Tier2Response,
)
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.zone import Zone
from ciu_agent.platform.interface import WindowInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ProcessFrameResult:
    """Outcome of processing a single frame through the canvas mapper.

    Attributes:
        classification: The change classification from the state
            classifier.
        tier_used: The analysis tier that was actually executed
            (0, 1, or 2).
        zones_added: Number of new zones registered.
        zones_updated: Number of existing zones whose state was
            refreshed.
        zones_removed: Number of stale zones expired or deleted.
        total_zones: Total zones in the registry after processing.
        processing_time_ms: Wall-clock time spent in ``process_frame``,
            in milliseconds.
        tier2_response: If tier 2 was invoked, the raw ``Tier2Response``;
            ``None`` otherwise.
        tier1_analyses: If tier 1 was invoked, the list of
            ``RegionAnalysis`` results; empty otherwise.
        skipped: ``True`` when the classifier recommended waiting for
            stability and the frame was not analysed further.
    """

    classification: ChangeClassification
    tier_used: int = 0
    zones_added: int = 0
    zones_updated: int = 0
    zones_removed: int = 0
    total_zones: int = 0
    processing_time_ms: float = 0.0
    tier2_response: Tier2Response | None = None
    tier1_analyses: list[RegionAnalysis] = field(default_factory=list)
    skipped: bool = False


# ---------------------------------------------------------------------------
# Canvas Mapper
# ---------------------------------------------------------------------------


class CanvasMapper:
    """Orchestrator that wires analysis tiers and the zone registry.

    All dependencies are injected via the constructor.  Each tier
    analyser can be replaced independently without affecting the
    orchestrator or the other tiers.

    Args:
        settings: Immutable application configuration.
        registry: The shared zone registry to read from and write to.
        classifier: The state-change classifier that decides which
            tier should handle each frame diff.
        tier1: The local region analyser (OpenCV).
        tier2: The full-screen API analyser (Claude vision).
    """

    def __init__(
        self,
        settings: Settings,
        registry: ZoneRegistry,
        classifier: StateClassifier,
        tier1: Tier1Analyzer,
        tier2: Tier2Analyzer,
    ) -> None:
        """Initialize with all injected dependencies.

        Args:
            settings: Configuration governing zone confidence,
                expiry, and stability timing.
            registry: Zone registry for CRUD operations.
            classifier: Heuristic tier router.
            tier1: Local OpenCV analyser.
            tier2: Claude API vision analyser.
        """
        self._settings = settings
        self._registry = registry
        self._classifier = classifier
        self._tier1 = tier1
        self._tier2 = tier2
        self._last_process_time: float = 0.0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def registry(self) -> ZoneRegistry:
        """The underlying zone registry."""
        return self._registry

    @property
    def last_process_time_ms(self) -> float:
        """Wall-clock time of the most recent ``process_frame`` call."""
        return self._last_process_time

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_frame(
        self,
        current_frame: NDArray[np.uint8],
        previous_frame: NDArray[np.uint8],
        diff: DiffResult,
        cursor_pos: tuple[int, int],
        active_window: WindowInfo | None = None,
    ) -> ProcessFrameResult:
        """Process a captured frame through the analysis pipeline.

        Steps:

        1. Classify the diff to determine tier and change type.
        2. If the classifier recommends waiting (animation settling),
           return early with ``skipped=True``.
        3. Route to the appropriate tier handler.
        4. Expire stale zones.
        5. Return the result summary.

        Args:
            current_frame: The current screenshot (BGR uint8).
            previous_frame: The previous screenshot (BGR uint8).
            diff: Pre-computed Tier 0 diff result from the capture
                engine.
            cursor_pos: Current cursor ``(x, y)`` in screen pixels.
            active_window: The focused window, or ``None``.

        Returns:
            A ``ProcessFrameResult`` summarising what happened.
        """
        start_ns = time.monotonic_ns()

        # 1. Classify
        classification = self._classifier.classify(
            diff=diff,
            cursor_pos=cursor_pos,
            active_window=active_window,
        )

        # 2. Stability wait — skip this frame if the classifier says
        #    to let animations settle.
        if classification.should_wait:
            elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
            self._last_process_time = elapsed_ms
            return ProcessFrameResult(
                classification=classification,
                tier_used=classification.tier,
                total_zones=self._registry.count,
                processing_time_ms=elapsed_ms,
                skipped=True,
            )

        # 3. Route to the appropriate tier handler.
        if classification.tier == 0:
            result = self._handle_tier0(classification)
        elif classification.tier == 1:
            result = self._handle_tier1(
                classification,
                current_frame,
                previous_frame,
            )
        else:
            result = self._handle_tier2(
                classification,
                current_frame,
            )

        # 4. Expire stale zones regardless of tier.
        expired = self._expire_stale_zones()
        result.zones_removed += len(expired)

        # 5. Finalize timing.
        elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
        result.processing_time_ms = elapsed_ms
        result.total_zones = self._registry.count
        self._last_process_time = elapsed_ms

        return result

    # ------------------------------------------------------------------
    # Tier handlers
    # ------------------------------------------------------------------

    def _handle_tier0(
        self,
        classification: ChangeClassification,
    ) -> ProcessFrameResult:
        """Handle a Tier 0 (no-op) classification.

        No analysis is performed — the diff engine already handled it.

        Args:
            classification: The change classification.

        Returns:
            A result with zero changes.
        """
        logger.debug(
            "Tier 0: %s — no analysis needed",
            classification.change_type.value,
        )
        return ProcessFrameResult(
            classification=classification,
            tier_used=0,
        )

    def _handle_tier1(
        self,
        classification: ChangeClassification,
        current_frame: NDArray[np.uint8],
        previous_frame: NDArray[np.uint8],
    ) -> ProcessFrameResult:
        """Handle a Tier 1 (local region analysis) classification.

        Runs ``Tier1Analyzer.analyze_region`` on each changed region
        reported by the classifier.  Results update the zone registry.

        Args:
            classification: The change classification with regions.
            current_frame: Current screenshot (BGR uint8).
            previous_frame: Previous screenshot (BGR uint8).

        Returns:
            A result summarising zone additions, updates, and removals.
        """
        analyses: list[RegionAnalysis] = []
        zones_added = 0
        zones_updated = 0
        zones_removed = 0

        existing_zones = self._registry.get_all()

        for region in classification.regions:
            analysis = self._tier1.analyze_region(
                current_frame=current_frame,
                previous_frame=previous_frame,
                region=region,
                existing_zones=existing_zones,
            )
            analyses.append(analysis)

            # Register new zones that meet the confidence floor.
            for zone in analysis.new_zones:
                if zone.confidence >= self._settings.min_zone_confidence * 0.5:
                    self._registry.register(zone)
                    zones_added += 1

            # Apply state updates to existing zones.
            for zone_id, changes in analysis.updated_zones:
                if self._registry.contains(zone_id):
                    self._registry.update(zone_id, **changes)
                    zones_updated += 1

            # Remove zones flagged as disappeared.
            for zone_id in analysis.removed_zone_ids:
                if self._registry.contains(zone_id):
                    self._registry.remove(zone_id)
                    zones_removed += 1

        logger.info(
            "Tier 1: %s — %d region(s), +%d /%d /-%d zones",
            classification.change_type.value,
            len(classification.regions),
            zones_added,
            zones_updated,
            zones_removed,
        )

        return ProcessFrameResult(
            classification=classification,
            tier_used=1,
            zones_added=zones_added,
            zones_updated=zones_updated,
            zones_removed=zones_removed,
            tier1_analyses=analyses,
        )

    def _handle_tier2(
        self,
        classification: ChangeClassification,
        current_frame: NDArray[np.uint8],
    ) -> ProcessFrameResult:
        """Handle a Tier 2 (full API analysis) classification.

        Encodes the frame as PNG, sends it to the Claude API via
        ``Tier2Analyzer.analyze_sync``, and replaces the entire zone
        registry with the API response.

        Args:
            classification: The change classification.
            current_frame: Current screenshot (BGR uint8).

        Returns:
            A result with the full zone set from the API.
        """
        # Encode frame to PNG.
        image_data = Tier2Analyzer.encode_frame(current_frame)
        h, w = current_frame.shape[:2]

        request = Tier2Request(
            image_data=image_data,
            screen_width=w,
            screen_height=h,
            context=f"Change type: {classification.change_type.value}",
        )

        # Use synchronous call (the orchestrator runs in a loop,
        # async is handled at a higher level if needed).
        response = self._tier2.analyze_sync(request)

        zones_added = 0
        zones_removed = 0

        if response.success:
            old_count = self._registry.count
            self._registry.replace_all(response.zones)
            zones_added = len(response.zones)
            zones_removed = old_count

            logger.info(
                "Tier 2: %s — replaced %d zones with %d from API "
                "(%.0f ms, %d tokens)",
                classification.change_type.value,
                old_count,
                zones_added,
                response.latency_ms,
                response.token_count,
            )
        else:
            logger.warning(
                "Tier 2: API call failed — %s", response.error,
            )

        return ProcessFrameResult(
            classification=classification,
            tier_used=2,
            zones_added=zones_added,
            zones_removed=zones_removed,
            tier2_response=response,
        )

    # ------------------------------------------------------------------
    # Zone lifecycle
    # ------------------------------------------------------------------

    def _expire_stale_zones(self) -> list[Zone]:
        """Remove zones that have not been seen recently.

        Uses ``Settings.zone_expiry_seconds`` as the maximum age.

        Returns:
            A list of zones that were expired.
        """
        now = time.time()
        expired = self._registry.expire_stale(
            current_time=now,
            max_age_seconds=self._settings.zone_expiry_seconds,
        )
        if expired:
            logger.debug(
                "Expired %d stale zone(s)", len(expired),
            )
        return expired

    # ------------------------------------------------------------------
    # Convenience queries (delegates to registry)
    # ------------------------------------------------------------------

    def get_zones_at_cursor(
        self,
        cursor_x: int,
        cursor_y: int,
    ) -> list[Zone]:
        """Find zones under the cursor position.

        Args:
            cursor_x: X coordinate in screen pixels.
            cursor_y: Y coordinate in screen pixels.

        Returns:
            Zones containing the point, smallest-first.
        """
        return self._registry.find_at_point(cursor_x, cursor_y)

    def get_all_zones(self) -> list[Zone]:
        """Return all zones currently in the registry.

        Returns:
            A list of all registered zones.
        """
        return self._registry.get_all()

    @property
    def zone_count(self) -> int:
        """Number of zones currently tracked."""
        return self._registry.count

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """Human-readable summary."""
        return (
            f"CanvasMapper(zones={self._registry.count}, "
            f"last_process={self._last_process_time:.1f}ms)"
        )
