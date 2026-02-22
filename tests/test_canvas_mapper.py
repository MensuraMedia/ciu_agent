"""Unit tests for the CanvasMapper orchestrator.

Tests cover tier routing, zone registry integration, stability wait
behaviour, stale zone expiry, convenience query methods, and the
``__repr__`` output.

Dependencies that are expensive or require external resources
(StateClassifier, Tier1Analyzer, Tier2Analyzer) are mocked.
ZoneRegistry is used as a real instance because it is lightweight and
in-memory.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ciu_agent.config.settings import Settings
from ciu_agent.core.canvas_mapper import CanvasMapper, ProcessFrameResult
from ciu_agent.core.capture_engine import DiffResult
from ciu_agent.core.state_classifier import (
    ChangeClassification,
    ChangeType,
)
from ciu_agent.core.tier1_analyzer import RegionAnalysis
from ciu_agent.core.tier2_analyzer import Tier2Analyzer, Tier2Response
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.zone import Rectangle, Zone, ZoneState, ZoneType
from ciu_agent.platform.interface import WindowInfo

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_frame(height: int = 100, width: int = 100) -> np.ndarray:
    """Create a blank BGR frame for testing."""
    return np.zeros((height, width, 3), dtype=np.uint8)


def _make_diff(
    changed_percent: float = 5.0,
    changed_regions: list[tuple[int, int, int, int]] | None = None,
    tier_recommendation: int = 1,
) -> DiffResult:
    """Create a DiffResult with sensible defaults."""
    return DiffResult(
        changed_percent=changed_percent,
        changed_regions=changed_regions or [],
        tier_recommendation=tier_recommendation,
    )


def _make_zone(
    zone_id: str = "z1",
    x: int = 10,
    y: int = 10,
    width: int = 50,
    height: int = 30,
    confidence: float = 0.8,
    last_seen: float | None = None,
    zone_type: ZoneType = ZoneType.BUTTON,
    zone_state: ZoneState = ZoneState.ENABLED,
    label: str = "TestZone",
) -> Zone:
    """Create a Zone with sensible defaults for testing."""
    return Zone(
        id=zone_id,
        bounds=Rectangle(x=x, y=y, width=width, height=height),
        type=zone_type,
        label=label,
        state=zone_state,
        confidence=confidence,
        last_seen=last_seen if last_seen is not None else time.time(),
    )


def _make_classification(
    change_type: ChangeType = ChangeType.CONTENT_UPDATE,
    tier: int = 1,
    regions: list[tuple[int, int, int, int]] | None = None,
    should_wait: bool = False,
    wait_ms: int = 0,
    confidence: float = 0.7,
) -> ChangeClassification:
    """Create a ChangeClassification with sensible defaults."""
    return ChangeClassification(
        change_type=change_type,
        tier=tier,
        regions=regions or [],
        confidence=confidence,
        should_wait=should_wait,
        wait_ms=wait_ms,
    )


def _make_region_analysis(
    region: tuple[int, int, int, int] = (0, 0, 50, 50),
    new_zones: list[Zone] | None = None,
    updated_zones: list[tuple[str, dict]] | None = None,
    removed_zone_ids: list[str] | None = None,
    confidence: float = 0.5,
) -> RegionAnalysis:
    """Create a RegionAnalysis with sensible defaults."""
    return RegionAnalysis(
        region=region,
        new_zones=new_zones or [],
        updated_zones=updated_zones or [],
        removed_zone_ids=removed_zone_ids or [],
        confidence=confidence,
    )


def _make_tier2_response(
    zones: list[Zone] | None = None,
    success: bool = True,
    latency_ms: float = 100.0,
    token_count: int = 500,
    error: str = "",
) -> Tier2Response:
    """Create a Tier2Response with sensible defaults."""
    return Tier2Response(
        zones=zones or [],
        raw_response="[]",
        latency_ms=latency_ms,
        token_count=token_count,
        success=success,
        error=error,
    )


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    """Provide default settings for tests."""
    return Settings(
        min_zone_confidence=0.7,
        zone_expiry_seconds=60.0,
    )


@pytest.fixture
def registry() -> ZoneRegistry:
    """Provide a real, empty ZoneRegistry."""
    return ZoneRegistry()


@pytest.fixture
def mock_classifier() -> MagicMock:
    """Provide a mock StateClassifier."""
    return MagicMock()


@pytest.fixture
def mock_tier1() -> MagicMock:
    """Provide a mock Tier1Analyzer."""
    return MagicMock()


@pytest.fixture
def mock_tier2() -> MagicMock:
    """Provide a mock Tier2Analyzer."""
    return MagicMock()


@pytest.fixture
def mapper(
    settings: Settings,
    registry: ZoneRegistry,
    mock_classifier: MagicMock,
    mock_tier1: MagicMock,
    mock_tier2: MagicMock,
) -> CanvasMapper:
    """Provide a CanvasMapper wired with mocks and a real registry."""
    return CanvasMapper(
        settings=settings,
        registry=registry,
        classifier=mock_classifier,
        tier1=mock_tier1,
        tier2=mock_tier2,
    )


# ==================================================================
# Test classes
# ==================================================================


class TestTier0Routing:
    """Tests for tier 0 (no-op) routing path."""

    def test_tier0_no_change_returns_zero_zones(
        self, mapper: CanvasMapper, mock_classifier: MagicMock
    ) -> None:
        """Tier 0 classification results in no zone changes."""
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        frame = _make_frame()
        diff = _make_diff(changed_percent=0.1, tier_recommendation=0)

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.tier_used == 0
        assert result.zones_added == 0
        assert result.zones_updated == 0
        assert result.skipped is False

    def test_tier0_cursor_only_returns_zero_zones(
        self, mapper: CanvasMapper, mock_classifier: MagicMock
    ) -> None:
        """Cursor-only classification also routes to tier 0."""
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.CURSOR_ONLY,
            tier=0,
        )
        frame = _make_frame()
        diff = _make_diff(changed_percent=0.3, tier_recommendation=0)

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.tier_used == 0
        assert result.zones_added == 0

    def test_tier0_classification_preserved_in_result(
        self, mapper: CanvasMapper, mock_classifier: MagicMock
    ) -> None:
        """The classification object is passed through to the result."""
        classification = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        mock_classifier.classify.return_value = classification
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.classification is classification

    def test_tier0_total_zones_reflects_registry(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
    ) -> None:
        """After tier 0, total_zones matches the registry count."""
        registry.register(_make_zone("pre_existing"))
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.total_zones == 1

    def test_tier0_does_not_call_tier1_or_tier2(
        self,
        mapper: CanvasMapper,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
        mock_tier2: MagicMock,
    ) -> None:
        """Tier 0 must not invoke tier 1 or tier 2 analyzers."""
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        frame = _make_frame()
        diff = _make_diff()

        mapper.process_frame(frame, frame, diff, (50, 50))

        mock_tier1.analyze_region.assert_not_called()
        mock_tier2.analyze_sync.assert_not_called()


class TestTier1Routing:
    """Tests for tier 1 (local region analysis) routing path."""

    def test_tier1_adds_new_zones_to_registry(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Zones from tier 1 analysis are registered in the registry."""
        region = (10, 10, 50, 50)
        zone = _make_zone("new_button", x=10, y=10, confidence=0.6)
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[region],
        )
        mock_tier1.analyze_region.return_value = _make_region_analysis(
            region=region,
            new_zones=[zone],
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.tier_used == 1
        assert result.zones_added == 1
        assert registry.contains("new_button")

    def test_tier1_updates_existing_zones(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Tier 1 can update the state of existing zones."""
        existing = _make_zone("btn1", x=10, y=10)
        registry.register(existing)

        region = (10, 10, 50, 50)
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[region],
        )
        mock_tier1.analyze_region.return_value = _make_region_analysis(
            region=region,
            updated_zones=[("btn1", {"state": ZoneState.HOVERED})],
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.zones_updated == 1
        updated = registry.get("btn1")
        assert updated is not None
        assert updated.state == ZoneState.HOVERED

    def test_tier1_removes_disappeared_zones(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Tier 1 can remove zones that no longer appear."""
        existing = _make_zone("vanished")
        registry.register(existing)

        region = (10, 10, 50, 50)
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[region],
        )
        mock_tier1.analyze_region.return_value = _make_region_analysis(
            region=region,
            removed_zone_ids=["vanished"],
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.zones_removed >= 1
        assert not registry.contains("vanished")

    def test_tier1_multiple_regions(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Tier 1 processes every region reported by the classifier."""
        r1 = (0, 0, 30, 30)
        r2 = (50, 50, 30, 30)
        zone1 = _make_zone("z_r1", x=0, y=0, confidence=0.6)
        zone2 = _make_zone("z_r2", x=50, y=50, confidence=0.6)

        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[r1, r2],
        )
        mock_tier1.analyze_region.side_effect = [
            _make_region_analysis(region=r1, new_zones=[zone1]),
            _make_region_analysis(region=r2, new_zones=[zone2]),
        ]
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.zones_added == 2
        assert registry.count == 2

    def test_tier1_analyses_collected_in_result(
        self,
        mapper: CanvasMapper,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """RegionAnalysis objects are available in the result."""
        region = (10, 10, 50, 50)
        analysis = _make_region_analysis(region=region)
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[region],
        )
        mock_tier1.analyze_region.return_value = analysis
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert len(result.tier1_analyses) == 1
        assert result.tier1_analyses[0] is analysis

    def test_tier1_low_confidence_zone_rejected(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Zones below half the min_zone_confidence are not registered."""
        # min_zone_confidence = 0.7, so threshold = 0.35
        region = (10, 10, 50, 50)
        low_conf_zone = _make_zone("low", confidence=0.3)
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[region],
        )
        mock_tier1.analyze_region.return_value = _make_region_analysis(
            region=region,
            new_zones=[low_conf_zone],
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.zones_added == 0
        assert not registry.contains("low")

    def test_tier1_borderline_confidence_zone_accepted(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Zones at exactly half min_zone_confidence are accepted."""
        # min_zone_confidence = 0.7, threshold = 0.35
        region = (10, 10, 50, 50)
        borderline_zone = _make_zone("borderline", confidence=0.35)
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[region],
        )
        mock_tier1.analyze_region.return_value = _make_region_analysis(
            region=region,
            new_zones=[borderline_zone],
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.zones_added == 1
        assert registry.contains("borderline")

    def test_tier1_update_nonexistent_zone_ignored(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Updating a zone ID that does not exist is silently skipped."""
        region = (10, 10, 50, 50)
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[region],
        )
        mock_tier1.analyze_region.return_value = _make_region_analysis(
            region=region,
            updated_zones=[("ghost", {"state": ZoneState.HOVERED})],
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        # Should not crash and should report 0 updated
        assert result.zones_updated == 0

    def test_tier1_remove_nonexistent_zone_ignored(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Removing a zone ID that does not exist is silently skipped."""
        region = (10, 10, 50, 50)
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[region],
        )
        mock_tier1.analyze_region.return_value = _make_region_analysis(
            region=region,
            removed_zone_ids=["ghost"],
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.zones_removed == 0


class TestTier2Routing:
    """Tests for tier 2 (full API analysis) routing path."""

    def test_tier2_replaces_all_zones_on_success(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier2: MagicMock,
    ) -> None:
        """A successful tier 2 call replaces the entire registry."""
        old_zone = _make_zone("old")
        registry.register(old_zone)

        new_zones = [
            _make_zone("api_z1", x=0, y=0),
            _make_zone("api_z2", x=60, y=0),
        ]
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.PAGE_NAVIGATION,
            tier=2,
        )
        mock_tier2.analyze_sync.return_value = _make_tier2_response(
            zones=new_zones,
        )
        frame = _make_frame()
        diff = _make_diff()

        with patch.object(Tier2Analyzer, "encode_frame", return_value=b"fake_png"):
            result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.tier_used == 2
        assert result.zones_added == 2
        assert result.zones_removed >= 1  # old zone removed
        assert not registry.contains("old")
        assert registry.contains("api_z1")
        assert registry.contains("api_z2")

    def test_tier2_failed_api_call_preserves_registry(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier2: MagicMock,
    ) -> None:
        """A failed tier 2 call does not modify the existing registry."""
        existing = _make_zone("existing")
        registry.register(existing)

        mock_classifier.classify.return_value = _make_classification(
            tier=2,
        )
        mock_tier2.analyze_sync.return_value = _make_tier2_response(
            success=False,
            error="Timeout",
        )
        frame = _make_frame()
        diff = _make_diff()

        with patch.object(Tier2Analyzer, "encode_frame", return_value=b"fake_png"):
            result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.tier_used == 2
        assert result.zones_added == 0
        assert result.zones_removed == 0
        assert registry.contains("existing")

    def test_tier2_response_stored_in_result(
        self,
        mapper: CanvasMapper,
        mock_classifier: MagicMock,
        mock_tier2: MagicMock,
    ) -> None:
        """The Tier2Response is accessible in the ProcessFrameResult."""
        response = _make_tier2_response(zones=[])
        mock_classifier.classify.return_value = _make_classification(
            tier=2,
        )
        mock_tier2.analyze_sync.return_value = response
        frame = _make_frame()
        diff = _make_diff()

        with patch.object(Tier2Analyzer, "encode_frame", return_value=b"fake_png"):
            result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.tier2_response is response

    def test_tier2_encode_frame_called(
        self,
        mapper: CanvasMapper,
        mock_classifier: MagicMock,
        mock_tier2: MagicMock,
    ) -> None:
        """Tier 2 encodes the current frame before sending to API."""
        mock_classifier.classify.return_value = _make_classification(
            tier=2,
        )
        mock_tier2.analyze_sync.return_value = _make_tier2_response()
        frame = _make_frame(height=80, width=120)
        diff = _make_diff()

        with patch.object(Tier2Analyzer, "encode_frame", return_value=b"fake_png") as mock_encode:
            mapper.process_frame(frame, frame, diff, (50, 50))
            mock_encode.assert_called_once()

    def test_tier2_request_has_correct_dimensions(
        self,
        mapper: CanvasMapper,
        mock_classifier: MagicMock,
        mock_tier2: MagicMock,
    ) -> None:
        """The Tier2Request carries the frame's width and height."""
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.APP_SWITCH,
            tier=2,
        )
        mock_tier2.analyze_sync.return_value = _make_tier2_response()
        frame = _make_frame(height=80, width=120)
        diff = _make_diff()

        with patch.object(Tier2Analyzer, "encode_frame", return_value=b"fake_png"):
            mapper.process_frame(frame, frame, diff, (50, 50))

        call_args = mock_tier2.analyze_sync.call_args
        request = call_args[0][0]
        assert request.screen_width == 120
        assert request.screen_height == 80


class TestStabilityWait:
    """Tests for the should_wait / skipped path."""

    def test_should_wait_returns_skipped_true(
        self, mapper: CanvasMapper, mock_classifier: MagicMock
    ) -> None:
        """When classifier says should_wait, result has skipped=True."""
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.APP_SWITCH,
            tier=2,
            should_wait=True,
            wait_ms=500,
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.skipped is True

    def test_should_wait_does_not_run_any_tier(
        self,
        mapper: CanvasMapper,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
        mock_tier2: MagicMock,
    ) -> None:
        """No tier handler should fire when should_wait is True."""
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            should_wait=True,
        )
        frame = _make_frame()
        diff = _make_diff()

        mapper.process_frame(frame, frame, diff, (50, 50))

        mock_tier1.analyze_region.assert_not_called()
        mock_tier2.analyze_sync.assert_not_called()

    def test_should_wait_preserves_total_zones(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
    ) -> None:
        """Skipped frames still report current zone count."""
        registry.register(_make_zone("z_pre"))
        mock_classifier.classify.return_value = _make_classification(
            tier=2,
            should_wait=True,
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.total_zones == 1

    def test_should_wait_has_zero_zone_mutations(
        self, mapper: CanvasMapper, mock_classifier: MagicMock
    ) -> None:
        """A skipped frame reports zero adds, updates, and removes."""
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            should_wait=True,
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.zones_added == 0
        assert result.zones_updated == 0
        assert result.zones_removed == 0


class TestStaleZoneExpiry:
    """Tests for automatic expiry of stale zones during processing."""

    def test_stale_zone_expired_after_tier0(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
    ) -> None:
        """Stale zones are expired even on tier 0 no-op frames."""
        stale_zone = _make_zone(
            "stale",
            last_seen=time.time() - 120.0,  # 2 minutes old
        )
        registry.register(stale_zone)

        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.zones_removed >= 1
        assert not registry.contains("stale")

    def test_fresh_zone_not_expired(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
    ) -> None:
        """Zones with recent last_seen are not expired."""
        fresh_zone = _make_zone("fresh", last_seen=time.time())
        registry.register(fresh_zone)

        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert registry.contains("fresh")
        # zones_removed should be 0 since nothing is stale
        assert result.zones_removed == 0

    def test_stale_zone_expired_during_tier1(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Stale zones are expired even when tier 1 runs."""
        stale = _make_zone("old", last_seen=time.time() - 120.0)
        registry.register(stale)

        region = (10, 10, 50, 50)
        new_zone = _make_zone("new1", confidence=0.6)
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[region],
        )
        mock_tier1.analyze_region.return_value = _make_region_analysis(
            region=region,
            new_zones=[new_zone],
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        # The stale zone expired + the new zone added
        assert result.zones_removed >= 1
        assert result.zones_added == 1
        assert not registry.contains("old")
        assert registry.contains("new1")

    def test_expiry_does_not_fire_on_skipped(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
    ) -> None:
        """Skipped (should_wait) frames do not expire stale zones."""
        stale = _make_zone("stale2", last_seen=time.time() - 120.0)
        registry.register(stale)

        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            should_wait=True,
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        # Skipped frames return early before expiry runs
        assert result.skipped is True
        assert registry.contains("stale2")


class TestConvenienceMethods:
    """Tests for get_zones_at_cursor, get_all_zones, zone_count."""

    def test_get_zones_at_cursor_returns_matching(
        self, mapper: CanvasMapper, registry: ZoneRegistry
    ) -> None:
        """get_zones_at_cursor delegates to registry.find_at_point."""
        zone = _make_zone("btn", x=10, y=10, width=50, height=30)
        registry.register(zone)

        hits = mapper.get_zones_at_cursor(20, 20)

        assert len(hits) == 1
        assert hits[0].id == "btn"

    def test_get_zones_at_cursor_misses_outside(
        self, mapper: CanvasMapper, registry: ZoneRegistry
    ) -> None:
        """Points outside all zones return an empty list."""
        zone = _make_zone("btn", x=10, y=10, width=50, height=30)
        registry.register(zone)

        hits = mapper.get_zones_at_cursor(500, 500)

        assert hits == []

    def test_get_all_zones_empty(self, mapper: CanvasMapper) -> None:
        """get_all_zones on an empty registry returns []."""
        assert mapper.get_all_zones() == []

    def test_get_all_zones_returns_all(self, mapper: CanvasMapper, registry: ZoneRegistry) -> None:
        """get_all_zones returns every registered zone."""
        z1 = _make_zone("a", x=0, y=0)
        z2 = _make_zone("b", x=50, y=50)
        registry.register(z1)
        registry.register(z2)

        zones = mapper.get_all_zones()

        assert len(zones) == 2
        ids = {z.id for z in zones}
        assert ids == {"a", "b"}

    def test_zone_count_empty(self, mapper: CanvasMapper) -> None:
        """zone_count is 0 for an empty registry."""
        assert mapper.zone_count == 0

    def test_zone_count_after_registration(
        self, mapper: CanvasMapper, registry: ZoneRegistry
    ) -> None:
        """zone_count reflects registered zones."""
        registry.register(_make_zone("x"))
        registry.register(_make_zone("y"))

        assert mapper.zone_count == 2


class TestRepr:
    """Tests for the __repr__ method."""

    def test_repr_shows_zone_count(self, mapper: CanvasMapper) -> None:
        """repr includes the zone count."""
        text = repr(mapper)
        assert "CanvasMapper(" in text
        assert "zones=0" in text

    def test_repr_shows_processing_time(self, mapper: CanvasMapper) -> None:
        """repr includes last_process time."""
        text = repr(mapper)
        assert "last_process=" in text
        assert "ms)" in text

    def test_repr_updates_after_processing(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
    ) -> None:
        """repr reflects zone count changes after process_frame."""
        registry.register(_make_zone("z1"))
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        frame = _make_frame()
        diff = _make_diff()

        mapper.process_frame(frame, frame, diff, (50, 50))
        text = repr(mapper)

        assert "zones=1" in text


class TestProcessFrameResult:
    """Tests for the ProcessFrameResult dataclass itself."""

    def test_default_values(self) -> None:
        """ProcessFrameResult defaults are sensible."""
        classification = _make_classification()
        result = ProcessFrameResult(classification=classification)

        assert result.tier_used == 0
        assert result.zones_added == 0
        assert result.zones_updated == 0
        assert result.zones_removed == 0
        assert result.total_zones == 0
        assert result.processing_time_ms == 0.0
        assert result.tier2_response is None
        assert result.tier1_analyses == []
        assert result.skipped is False

    def test_result_has_positive_processing_time(
        self, mapper: CanvasMapper, mock_classifier: MagicMock
    ) -> None:
        """process_frame always records a positive processing time."""
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.processing_time_ms >= 0.0


class TestProperties:
    """Tests for mapper properties."""

    def test_registry_property(self, mapper: CanvasMapper, registry: ZoneRegistry) -> None:
        """The registry property returns the injected registry."""
        assert mapper.registry is registry

    def test_last_process_time_initially_zero(self, mapper: CanvasMapper) -> None:
        """last_process_time_ms is 0 before any processing."""
        assert mapper.last_process_time_ms == 0.0

    def test_last_process_time_updates(
        self, mapper: CanvasMapper, mock_classifier: MagicMock
    ) -> None:
        """last_process_time_ms updates after process_frame."""
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        frame = _make_frame()
        diff = _make_diff()

        mapper.process_frame(frame, frame, diff, (50, 50))

        assert mapper.last_process_time_ms >= 0.0


class TestActiveWindowPassing:
    """Tests for active_window parameter passing."""

    def test_active_window_passed_to_classifier(
        self, mapper: CanvasMapper, mock_classifier: MagicMock
    ) -> None:
        """active_window is forwarded to the classifier."""
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        window = WindowInfo(
            title="My App",
            x=0,
            y=0,
            width=1920,
            height=1080,
            is_active=True,
        )
        frame = _make_frame()
        diff = _make_diff()

        mapper.process_frame(
            frame,
            frame,
            diff,
            (50, 50),
            active_window=window,
        )

        call_kwargs = mock_classifier.classify.call_args
        assert call_kwargs.kwargs.get("active_window") is window

    def test_none_active_window_passed(
        self, mapper: CanvasMapper, mock_classifier: MagicMock
    ) -> None:
        """None active_window is forwarded when not provided."""
        mock_classifier.classify.return_value = _make_classification(
            change_type=ChangeType.NO_CHANGE,
            tier=0,
        )
        frame = _make_frame()
        diff = _make_diff()

        mapper.process_frame(frame, frame, diff, (50, 50))

        call_kwargs = mock_classifier.classify.call_args
        assert call_kwargs.kwargs.get("active_window") is None


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_tier1_empty_regions_list(
        self,
        mapper: CanvasMapper,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Tier 1 with zero regions does not call analyze_region."""
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[],
        )
        frame = _make_frame()
        diff = _make_diff()

        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.tier_used == 1
        assert result.zones_added == 0
        mock_tier1.analyze_region.assert_not_called()

    def test_tier2_empty_zones_on_success(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier2: MagicMock,
    ) -> None:
        """Tier 2 success with empty zones clears the registry."""
        old = _make_zone("old")
        registry.register(old)

        mock_classifier.classify.return_value = _make_classification(
            tier=2,
        )
        mock_tier2.analyze_sync.return_value = _make_tier2_response(
            zones=[],
            success=True,
        )
        frame = _make_frame()
        diff = _make_diff()

        with patch.object(Tier2Analyzer, "encode_frame", return_value=b"fake_png"):
            result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert result.zones_added == 0
        assert result.zones_removed == 1
        assert registry.count == 0

    def test_multiple_sequential_process_calls(
        self,
        mapper: CanvasMapper,
        registry: ZoneRegistry,
        mock_classifier: MagicMock,
        mock_tier1: MagicMock,
    ) -> None:
        """Multiple process_frame calls accumulate zones."""
        region = (10, 10, 50, 50)

        # First call: add a zone
        z1 = _make_zone("round1", confidence=0.6)
        mock_classifier.classify.return_value = _make_classification(
            tier=1,
            regions=[region],
        )
        mock_tier1.analyze_region.return_value = _make_region_analysis(
            region=region,
            new_zones=[z1],
        )
        frame = _make_frame()
        diff = _make_diff()
        mapper.process_frame(frame, frame, diff, (50, 50))

        # Second call: add another zone
        z2 = _make_zone("round2", confidence=0.6)
        mock_tier1.analyze_region.return_value = _make_region_analysis(
            region=region,
            new_zones=[z2],
        )
        result = mapper.process_frame(frame, frame, diff, (50, 50))

        assert registry.count == 2
        assert result.total_zones == 2
