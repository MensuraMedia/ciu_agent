"""Unit tests for the CaptureEngine, CaptureFrame, and DiffResult.

All tests use a ``MockPlatform`` that returns synthetic frames and fake
cursor positions, so no live screen or display server is required.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from ciu_agent.config.settings import Settings
from ciu_agent.core.capture_engine import (
    CaptureEngine,
    CaptureFrame,
    DiffResult,
)
from ciu_agent.platform.interface import PlatformInterface, WindowInfo

# ------------------------------------------------------------------
# Mock platform
# ------------------------------------------------------------------


class MockPlatform(PlatformInterface):
    """Mock platform for testing without a live display."""

    def __init__(self, width: int = 100, height: int = 80) -> None:
        self._width = width
        self._height = height
        self._cursor: tuple[int, int] = (50, 40)
        self._frame_color: tuple[int, int, int] = (128, 128, 128)

    # -- Test helpers ------------------------------------------------

    def set_cursor(self, x: int, y: int) -> None:
        """Set the fake cursor position returned by ``get_cursor_pos``."""
        self._cursor = (x, y)

    def set_frame_color(self, b: int, g: int, r: int) -> None:
        """Set the solid BGR colour returned by ``capture_frame``."""
        self._frame_color = (b, g, r)

    # -- PlatformInterface implementation ----------------------------

    def capture_frame(self) -> NDArray[np.uint8]:
        frame = np.full(
            (self._height, self._width, 3),
            self._frame_color,
            dtype=np.uint8,
        )
        return frame

    def get_cursor_pos(self) -> tuple[int, int]:
        return self._cursor

    def move_cursor(self, x: int, y: int) -> None:
        self._cursor = (x, y)

    def click(self, x: int, y: int, button: str = "left") -> None:
        pass

    def double_click(self, x: int, y: int, button: str = "left") -> None:
        pass

    def scroll(self, x: int, y: int, amount: int) -> None:
        pass

    def type_text(self, text: str) -> None:
        pass

    def key_press(self, key: str) -> None:
        pass

    def get_screen_size(self) -> tuple[int, int]:
        return (self._width, self._height)

    def get_active_window(self) -> WindowInfo:
        return WindowInfo(
            title="Mock Window",
            x=0,
            y=0,
            width=self._width,
            height=self._height,
            is_active=True,
            process_name="mock",
        )

    def list_windows(self) -> list[WindowInfo]:
        return [self.get_active_window()]

    def get_platform_name(self) -> str:
        return "mock"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def mock_platform() -> MockPlatform:
    """Return a fresh ``MockPlatform`` with default 100x80 dimensions."""
    return MockPlatform(width=100, height=80)


@pytest.fixture()
def default_settings() -> Settings:
    """Return ``Settings`` with defaults suitable for fast tests."""
    return Settings(
        target_fps=10,
        ring_buffer_seconds=2.0,
        diff_threshold_percent=0.5,
        tier2_threshold_percent=30.0,
    )


@pytest.fixture()
def engine(mock_platform: MockPlatform, default_settings: Settings) -> CaptureEngine:
    """Return a ``CaptureEngine`` wired to the mock platform."""
    return CaptureEngine(mock_platform, default_settings)


# ==================================================================
# Dataclass construction
# ==================================================================


class TestCaptureFrame:
    """Tests for the ``CaptureFrame`` dataclass."""

    def test_construction_stores_all_fields(self) -> None:
        """CaptureFrame should store image, cursor, timestamp, number."""
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        frame = CaptureFrame(
            image=img,
            cursor_x=5,
            cursor_y=7,
            timestamp=1.23,
            frame_number=0,
        )
        assert frame.cursor_x == 5
        assert frame.cursor_y == 7
        assert frame.timestamp == 1.23
        assert frame.frame_number == 0
        assert frame.image.shape == (10, 10, 3)

    def test_construction_image_dtype_preserved(self) -> None:
        """CaptureFrame should preserve the dtype of the image array."""
        img = np.ones((4, 4, 3), dtype=np.uint8) * 200
        frame = CaptureFrame(
            image=img,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=0,
        )
        assert frame.image.dtype == np.uint8


class TestDiffResult:
    """Tests for the ``DiffResult`` dataclass."""

    def test_construction_stores_all_fields(self) -> None:
        """DiffResult should store changed_percent, regions, tier."""
        result = DiffResult(
            changed_percent=12.5,
            changed_regions=[(10, 20, 30, 40)],
            tier_recommendation=1,
        )
        assert result.changed_percent == 12.5
        assert result.changed_regions == [(10, 20, 30, 40)]
        assert result.tier_recommendation == 1

    def test_construction_empty_regions(self) -> None:
        """DiffResult should accept an empty regions list."""
        result = DiffResult(
            changed_percent=0.0,
            changed_regions=[],
            tier_recommendation=0,
        )
        assert result.changed_regions == []
        assert result.tier_recommendation == 0


# ==================================================================
# Buffer capacity and state
# ==================================================================


class TestBufferCapacity:
    """Tests for ring buffer sizing and initial state."""

    def test_buffer_capacity_matches_settings(
        self, engine: CaptureEngine, default_settings: Settings
    ) -> None:
        """Capacity should equal ring_buffer_seconds * target_fps."""
        expected = int(default_settings.ring_buffer_seconds * default_settings.target_fps)
        assert engine.buffer_capacity == expected

    def test_buffer_capacity_custom_settings(self, mock_platform: MockPlatform) -> None:
        """Capacity should respect non-default settings."""
        settings = Settings(target_fps=30, ring_buffer_seconds=10.0)
        eng = CaptureEngine(mock_platform, settings)
        assert eng.buffer_capacity == 300

    def test_buffer_starts_empty(self, engine: CaptureEngine) -> None:
        """A new engine should have an empty buffer."""
        assert engine.buffer_size == 0


# ==================================================================
# capture_single
# ==================================================================


class TestCaptureSingle:
    """Tests for ``CaptureEngine.capture_single``."""

    def test_capture_single_returns_captureframe(self, engine: CaptureEngine) -> None:
        """capture_single should return a CaptureFrame instance."""
        frame = engine.capture_single()
        assert isinstance(frame, CaptureFrame)

    def test_capture_single_correct_shape(self, engine: CaptureEngine) -> None:
        """Returned frame image should match the mock screen size."""
        frame = engine.capture_single()
        assert frame.image.shape == (80, 100, 3)

    def test_capture_single_correct_cursor(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """Returned frame should carry the current cursor coords."""
        mock_platform.set_cursor(77, 33)
        frame = engine.capture_single()
        assert frame.cursor_x == 77
        assert frame.cursor_y == 33

    def test_capture_single_does_not_add_to_buffer(self, engine: CaptureEngine) -> None:
        """capture_single must NOT store the frame in the buffer."""
        engine.capture_single()
        assert engine.buffer_size == 0

    def test_capture_single_has_monotonic_timestamp(self, engine: CaptureEngine) -> None:
        """Timestamps should be monotonically increasing."""
        f1 = engine.capture_single()
        f2 = engine.capture_single()
        assert f2.timestamp >= f1.timestamp


# ==================================================================
# capture_to_buffer
# ==================================================================


class TestCaptureToBuffer:
    """Tests for ``CaptureEngine.capture_to_buffer``."""

    def test_capture_to_buffer_adds_frame(self, engine: CaptureEngine) -> None:
        """capture_to_buffer should increase the buffer size by one."""
        engine.capture_to_buffer()
        assert engine.buffer_size == 1

    def test_capture_to_buffer_returns_frame(self, engine: CaptureEngine) -> None:
        """capture_to_buffer should return the captured CaptureFrame."""
        frame = engine.capture_to_buffer()
        assert isinstance(frame, CaptureFrame)
        assert frame.image.shape == (80, 100, 3)

    def test_buffer_evicts_oldest_when_full(
        self,
        mock_platform: MockPlatform,
    ) -> None:
        """When the buffer is full, oldest frame should be evicted."""
        settings = Settings(target_fps=1, ring_buffer_seconds=3.0)
        eng = CaptureEngine(mock_platform, settings)
        assert eng.buffer_capacity == 3

        f0 = eng.capture_to_buffer()  # frame_number=0
        eng.capture_to_buffer()  # frame_number=1
        eng.capture_to_buffer()  # frame_number=2
        assert eng.buffer_size == 3

        # Fourth capture should evict the very first frame.
        eng.capture_to_buffer()  # frame_number=3
        assert eng.buffer_size == 3

        frames = eng.get_buffer_frames()
        numbers = [f.frame_number for f in frames]
        assert numbers == [1, 2, 3]
        assert f0.frame_number not in numbers

    def test_multiple_captures_grow_buffer(self, engine: CaptureEngine) -> None:
        """Buffer size should grow with each capture_to_buffer call."""
        for i in range(5):
            engine.capture_to_buffer()
        assert engine.buffer_size == 5


# ==================================================================
# Buffer access
# ==================================================================


class TestBufferAccess:
    """Tests for get_latest_frame, get_buffer_frames, clear_buffer."""

    def test_get_latest_frame_empty_returns_none(self, engine: CaptureEngine) -> None:
        """get_latest_frame should return None on an empty buffer."""
        assert engine.get_latest_frame() is None

    def test_get_latest_frame_returns_most_recent(self, engine: CaptureEngine) -> None:
        """get_latest_frame should return the newest buffered frame."""
        engine.capture_to_buffer()
        engine.capture_to_buffer()
        latest = engine.capture_to_buffer()

        retrieved = engine.get_latest_frame()
        assert retrieved is not None
        assert retrieved.frame_number == latest.frame_number

    def test_get_buffer_frames_oldest_first(self, engine: CaptureEngine) -> None:
        """get_buffer_frames should return frames oldest-first."""
        f1 = engine.capture_to_buffer()
        f2 = engine.capture_to_buffer()
        f3 = engine.capture_to_buffer()

        frames = engine.get_buffer_frames()
        assert len(frames) == 3
        assert frames[0].frame_number == f1.frame_number
        assert frames[1].frame_number == f2.frame_number
        assert frames[2].frame_number == f3.frame_number

    def test_clear_buffer_empties_buffer(self, engine: CaptureEngine) -> None:
        """clear_buffer should remove all frames."""
        engine.capture_to_buffer()
        engine.capture_to_buffer()
        assert engine.buffer_size == 2

        engine.clear_buffer()
        assert engine.buffer_size == 0
        assert engine.get_latest_frame() is None

    def test_clear_buffer_does_not_reset_frame_counter(self, engine: CaptureEngine) -> None:
        """Frame numbers should keep incrementing after a clear."""
        engine.capture_to_buffer()  # frame 0
        engine.capture_to_buffer()  # frame 1
        engine.clear_buffer()

        frame = engine.capture_to_buffer()  # frame 2
        assert frame.frame_number == 2


# ==================================================================
# Frame number incrementing
# ==================================================================


class TestFrameNumber:
    """Tests for sequential frame_number tracking."""

    def test_frame_number_increments_across_captures(self, engine: CaptureEngine) -> None:
        """Each call to capture should yield an incrementing number."""
        numbers = []
        for _ in range(5):
            f = engine.capture_single()
            numbers.append(f.frame_number)
        assert numbers == [0, 1, 2, 3, 4]

    def test_frame_number_shared_between_methods(self, engine: CaptureEngine) -> None:
        """capture_single and capture_to_buffer share the counter."""
        f0 = engine.capture_single()  # 0
        f1 = engine.capture_to_buffer()  # 1
        f2 = engine.capture_single()  # 2
        f3 = engine.capture_to_buffer()  # 3

        assert f0.frame_number == 0
        assert f1.frame_number == 1
        assert f2.frame_number == 2
        assert f3.frame_number == 3


# ==================================================================
# compute_diff
# ==================================================================


class TestComputeDiff:
    """Tests for Tier 0 frame differencing via ``compute_diff``."""

    def test_diff_identical_frames_zero_change_tier0(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """Identical frames should yield 0% changed and tier 0."""
        mock_platform.set_frame_color(100, 100, 100)
        f1 = engine.capture_single()
        f2 = engine.capture_single()

        result = engine.compute_diff(f1, f2)
        assert result.changed_percent == pytest.approx(0.0)
        assert result.tier_recommendation == 0
        assert result.changed_regions == []

    def test_diff_completely_different_frames_tier2(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """Completely different frames should yield ~100% and tier 2."""
        mock_platform.set_frame_color(0, 0, 0)
        f1 = engine.capture_single()

        mock_platform.set_frame_color(255, 255, 255)
        f2 = engine.capture_single()

        result = engine.compute_diff(f1, f2)
        assert result.changed_percent == pytest.approx(100.0)
        assert result.tier_recommendation == 2
        assert len(result.changed_regions) > 0

    def test_diff_partial_change_tier1(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """A partial change between thresholds should yield tier 1."""
        # Start with a solid black frame.
        mock_platform.set_frame_color(0, 0, 0)
        f1 = engine.capture_single()

        # Build f2 manually: change ~10% of pixels to white.
        # With defaults: diff_threshold=0.5%, tier2_threshold=30%.
        # 10% falls between those two, so tier should be 1.
        img2 = np.zeros((80, 100, 3), dtype=np.uint8)
        # Change the first 8 rows (8/80 = 10%) to white.
        img2[:8, :, :] = 255
        f2 = CaptureFrame(
            image=img2,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=99,
        )

        result = engine.compute_diff(f1, f2)
        assert 5.0 < result.changed_percent < 15.0
        assert result.tier_recommendation == 1
        assert len(result.changed_regions) > 0

    def test_diff_below_threshold_tier0(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """A tiny change below diff_threshold_percent yields tier 0."""
        mock_platform.set_frame_color(100, 100, 100)
        f1 = engine.capture_single()

        # Change a single pixel well above the pixel intensity
        # threshold so it counts, but total area < 0.5%.
        img2 = f1.image.copy()
        img2[0, 0, :] = 255  # 1 pixel out of 8000 = 0.0125%
        f2 = CaptureFrame(
            image=img2,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=99,
        )

        result = engine.compute_diff(f1, f2)
        assert result.changed_percent < 0.5
        assert result.tier_recommendation == 0

    def test_diff_exactly_at_tier2_boundary(
        self,
        mock_platform: MockPlatform,
    ) -> None:
        """A change exactly at tier2_threshold_percent yields tier 2."""
        settings = Settings(
            target_fps=10,
            ring_buffer_seconds=2.0,
            diff_threshold_percent=0.5,
            tier2_threshold_percent=30.0,
        )
        eng = CaptureEngine(mock_platform, settings)

        mock_platform.set_frame_color(0, 0, 0)
        f1 = eng.capture_single()

        # Change exactly 30% of rows (24 out of 80) to white.
        img2 = np.zeros((80, 100, 3), dtype=np.uint8)
        img2[:24, :, :] = 255
        f2 = CaptureFrame(
            image=img2,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=99,
        )

        result = eng.compute_diff(f1, f2)
        assert result.changed_percent == pytest.approx(30.0)
        assert result.tier_recommendation == 2

    def test_diff_changed_regions_are_bounding_boxes(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """Changed regions should be (x, y, w, h) tuples."""
        mock_platform.set_frame_color(0, 0, 0)
        f1 = engine.capture_single()

        img2 = np.zeros((80, 100, 3), dtype=np.uint8)
        img2[10:20, 30:60, :] = 255
        f2 = CaptureFrame(
            image=img2,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=99,
        )

        result = engine.compute_diff(f1, f2)
        assert len(result.changed_regions) >= 1
        for region in result.changed_regions:
            assert len(region) == 4
            x, y, w, h = region
            assert w > 0
            assert h > 0

    def test_diff_single_region_matches_changed_area(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """A single rectangular change should produce one region."""
        mock_platform.set_frame_color(0, 0, 0)
        f1 = engine.capture_single()

        img2 = np.zeros((80, 100, 3), dtype=np.uint8)
        # Change a 30x10 rectangle starting at (30, 10).
        img2[10:20, 30:60, :] = 255
        f2 = CaptureFrame(
            image=img2,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=99,
        )

        result = engine.compute_diff(f1, f2)
        assert len(result.changed_regions) == 1
        x, y, w, h = result.changed_regions[0]
        assert x == 30
        assert y == 10
        assert w == 30
        assert h == 10

    def test_diff_two_disjoint_regions(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """Two separated changed areas should yield two regions."""
        mock_platform.set_frame_color(0, 0, 0)
        f1 = engine.capture_single()

        img2 = np.zeros((80, 100, 3), dtype=np.uint8)
        # Region A: rows 0-9, cols 0-9
        img2[0:10, 0:10, :] = 255
        # Region B: rows 60-69, cols 80-89 (well separated)
        img2[60:70, 80:90, :] = 255
        f2 = CaptureFrame(
            image=img2,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=99,
        )

        result = engine.compute_diff(f1, f2)
        assert len(result.changed_regions) == 2

    def test_diff_subtle_change_below_pixel_threshold_ignored(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """Changes below the pixel intensity threshold are noise."""
        mock_platform.set_frame_color(100, 100, 100)
        f1 = engine.capture_single()

        # Nudge every pixel by just 10 (below the default pixel
        # threshold of 25). The diff should register as zero.
        img2 = f1.image.copy()
        img2 = np.clip(img2.astype(np.int16) + 10, 0, 255).astype(np.uint8)
        f2 = CaptureFrame(
            image=img2,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=99,
        )

        result = engine.compute_diff(f1, f2)
        assert result.changed_percent == pytest.approx(0.0)
        assert result.tier_recommendation == 0
        assert result.changed_regions == []


# ==================================================================
# check_for_changes
# ==================================================================


class TestCheckForChanges:
    """Tests for the convenience ``check_for_changes`` method."""

    def test_check_for_changes_empty_buffer_returns_none(self, engine: CaptureEngine) -> None:
        """check_for_changes with 0 frames should return None."""
        assert engine.check_for_changes() is None

    def test_check_for_changes_one_frame_returns_none(self, engine: CaptureEngine) -> None:
        """check_for_changes with only 1 frame should return None."""
        engine.capture_to_buffer()
        assert engine.check_for_changes() is None

    def test_check_for_changes_two_identical_frames(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """Two identical buffered frames should yield a DiffResult."""
        mock_platform.set_frame_color(50, 50, 50)
        engine.capture_to_buffer()
        engine.capture_to_buffer()

        result = engine.check_for_changes()
        assert result is not None
        assert isinstance(result, DiffResult)
        assert result.changed_percent == pytest.approx(0.0)
        assert result.tier_recommendation == 0

    def test_check_for_changes_two_different_frames(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """Two different buffered frames should detect the change."""
        mock_platform.set_frame_color(0, 0, 0)
        engine.capture_to_buffer()

        mock_platform.set_frame_color(255, 255, 255)
        engine.capture_to_buffer()

        result = engine.check_for_changes()
        assert result is not None
        assert result.changed_percent > 0.0
        assert result.tier_recommendation == 2

    def test_check_for_changes_uses_last_two_frames(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """check_for_changes should compare only the last two frames."""
        # Frame 0: black
        mock_platform.set_frame_color(0, 0, 0)
        engine.capture_to_buffer()

        # Frame 1: white (big diff from frame 0)
        mock_platform.set_frame_color(255, 255, 255)
        engine.capture_to_buffer()

        # Frame 2: white (identical to frame 1)
        engine.capture_to_buffer()

        result = engine.check_for_changes()
        assert result is not None
        # Comparing frame 1 and frame 2, both white -- no diff.
        assert result.changed_percent == pytest.approx(0.0)
        assert result.tier_recommendation == 0

    def test_check_for_changes_after_clear_returns_none(
        self,
        engine: CaptureEngine,
        mock_platform: MockPlatform,
    ) -> None:
        """After clearing the buffer, check_for_changes returns None."""
        mock_platform.set_frame_color(0, 0, 0)
        engine.capture_to_buffer()
        engine.capture_to_buffer()

        engine.clear_buffer()
        assert engine.check_for_changes() is None


# ==================================================================
# Tier classification edge cases
# ==================================================================


class TestTierClassification:
    """Tests for _classify_tier boundary behaviour via compute_diff."""

    def test_tier0_just_below_threshold(self, mock_platform: MockPlatform) -> None:
        """A change just under diff_threshold_percent is tier 0."""
        settings = Settings(
            target_fps=10,
            ring_buffer_seconds=2.0,
            diff_threshold_percent=10.0,
            tier2_threshold_percent=50.0,
        )
        eng = CaptureEngine(mock_platform, settings)

        mock_platform.set_frame_color(0, 0, 0)
        f1 = eng.capture_single()

        # Change 7 out of 80 rows = 8.75%  (< 10% threshold)
        img2 = np.zeros((80, 100, 3), dtype=np.uint8)
        img2[:7, :, :] = 255
        f2 = CaptureFrame(
            image=img2,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=99,
        )

        result = eng.compute_diff(f1, f2)
        assert result.changed_percent < 10.0
        assert result.tier_recommendation == 0

    def test_tier1_just_above_diff_threshold(self, mock_platform: MockPlatform) -> None:
        """A change just over diff_threshold_percent is tier 1."""
        settings = Settings(
            target_fps=10,
            ring_buffer_seconds=2.0,
            diff_threshold_percent=10.0,
            tier2_threshold_percent=50.0,
        )
        eng = CaptureEngine(mock_platform, settings)

        mock_platform.set_frame_color(0, 0, 0)
        f1 = eng.capture_single()

        # Change 9 out of 80 rows = 11.25%  (> 10%, < 50%)
        img2 = np.zeros((80, 100, 3), dtype=np.uint8)
        img2[:9, :, :] = 255
        f2 = CaptureFrame(
            image=img2,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=99,
        )

        result = eng.compute_diff(f1, f2)
        assert 10.0 < result.changed_percent < 50.0
        assert result.tier_recommendation == 1

    def test_tier2_just_at_boundary(self, mock_platform: MockPlatform) -> None:
        """A change at exactly tier2_threshold_percent is tier 2."""
        settings = Settings(
            target_fps=10,
            ring_buffer_seconds=2.0,
            diff_threshold_percent=10.0,
            tier2_threshold_percent=50.0,
        )
        eng = CaptureEngine(mock_platform, settings)

        mock_platform.set_frame_color(0, 0, 0)
        f1 = eng.capture_single()

        # Change 40 out of 80 rows = exactly 50%.
        img2 = np.zeros((80, 100, 3), dtype=np.uint8)
        img2[:40, :, :] = 255
        f2 = CaptureFrame(
            image=img2,
            cursor_x=0,
            cursor_y=0,
            timestamp=0.0,
            frame_number=99,
        )

        result = eng.compute_diff(f1, f2)
        assert result.changed_percent == pytest.approx(50.0)
        assert result.tier_recommendation == 2

    def test_tier2_well_above_boundary(self, mock_platform: MockPlatform) -> None:
        """A large change well above tier2 threshold is tier 2."""
        settings = Settings(
            target_fps=10,
            ring_buffer_seconds=2.0,
            diff_threshold_percent=5.0,
            tier2_threshold_percent=30.0,
        )
        eng = CaptureEngine(mock_platform, settings)

        mock_platform.set_frame_color(0, 0, 0)
        f1 = eng.capture_single()

        mock_platform.set_frame_color(255, 255, 255)
        f2 = eng.capture_single()

        result = eng.compute_diff(f1, f2)
        assert result.changed_percent > 30.0
        assert result.tier_recommendation == 2
