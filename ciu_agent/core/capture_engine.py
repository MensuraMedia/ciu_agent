"""Continuous screen capture and Tier 0 frame differencing engine.

The ``CaptureEngine`` grabs frames from the screen via an injected
``PlatformInterface``, stores them in a fixed-size ring buffer, and
provides lightweight frame-diff analysis to decide whether downstream
tiers need to re-examine the canvas.

Typical usage::

    from ciu_agent.platform.interface import create_platform
    from ciu_agent.config.settings import get_default_settings

    platform = create_platform()
    settings = get_default_settings()
    engine = CaptureEngine(platform, settings)

    frame = engine.capture_to_buffer()
    diff = engine.check_for_changes()  # None until >= 2 frames
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from ciu_agent.config.settings import Settings
from ciu_agent.platform.interface import PlatformInterface

# Pixel-intensity threshold used when binarising the absolute-diff
# image.  Pixel differences of this value or below are treated as
# noise and ignored.
_DIFF_PIXEL_THRESHOLD: int = 25


@dataclass
class CaptureFrame:
    """A single captured frame with metadata.

    Attributes:
        image: Screen grab as a NumPy array of shape ``(H, W, 3)``
            in BGR colour order with dtype ``uint8``.
        cursor_x: Horizontal cursor position in logical pixels.
        cursor_y: Vertical cursor position in logical pixels.
        timestamp: Monotonic timestamp (``time.monotonic()``) at
            the moment of capture.
        frame_number: Sequential frame index starting from ``0``.
    """

    image: NDArray[np.uint8]
    cursor_x: int
    cursor_y: int
    timestamp: float
    frame_number: int


@dataclass
class DiffResult:
    """Result of Tier 0 frame differencing.

    Attributes:
        changed_percent: Fraction of pixels that changed, expressed
            as a value between ``0.0`` and ``100.0``.
        changed_regions: Bounding boxes ``(x, y, w, h)`` of the
            contiguous changed areas found in the diff mask.
        tier_recommendation: Suggested analysis tier.

            * ``0`` -- no meaningful change; no further action.
            * ``1`` -- localised change; run Tier 1 region update.
            * ``2`` -- large-scale change; run full Tier 2 rebuild.
    """

    changed_percent: float
    changed_regions: list[tuple[int, int, int, int]]
    tier_recommendation: int


class CaptureEngine:
    """Continuous screen capture with ring buffer and frame diffing.

    The engine delegates the actual screen grab to a
    ``PlatformInterface`` and stores captured frames in a
    fixed-capacity ring buffer backed by ``collections.deque``.
    Frame differencing uses OpenCV operations that run entirely on
    the CPU, keeping the engine suitable for Intel UHD-class
    hardware.

    Args:
        platform: The platform-specific backend used for screen
            capture and cursor queries.
        settings: Immutable configuration object that controls FPS
            targets, buffer size, and diff thresholds.
    """

    def __init__(
        self,
        platform: PlatformInterface,
        settings: Settings,
    ) -> None:
        """Initialize with injected platform and settings.

        Args:
            platform: Platform backend for screen capture and
                cursor position queries.
            settings: Configuration governing buffer size and
                diff thresholds.
        """
        self._platform = platform
        self._settings = settings

        maxlen = int(settings.ring_buffer_seconds * settings.target_fps)
        self._buffer: deque[CaptureFrame] = deque(maxlen=maxlen)
        self._frame_counter: int = 0

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def capture_single(self) -> CaptureFrame:
        """Capture one frame with cursor position.

        The frame is **not** added to the ring buffer.  Use
        ``capture_to_buffer`` when you also want to store it.

        Returns:
            A ``CaptureFrame`` containing the screen image, cursor
            coordinates, a monotonic timestamp, and the sequential
            frame number.
        """
        image = self._platform.capture_frame()
        cursor_x, cursor_y = self._platform.get_cursor_pos()
        timestamp = time.monotonic()
        frame_number = self._frame_counter
        self._frame_counter += 1

        return CaptureFrame(
            image=image,
            cursor_x=cursor_x,
            cursor_y=cursor_y,
            timestamp=timestamp,
            frame_number=frame_number,
        )

    def capture_to_buffer(self) -> CaptureFrame:
        """Capture one frame, store it in the ring buffer, and return it.

        If the buffer is full the oldest frame is silently evicted.

        Returns:
            The newly captured ``CaptureFrame``.
        """
        frame = self.capture_single()
        self._buffer.append(frame)
        return frame

    # ------------------------------------------------------------------
    # Buffer access
    # ------------------------------------------------------------------

    def get_latest_frame(self) -> CaptureFrame | None:
        """Return the most recent frame in the ring buffer.

        Returns:
            The latest ``CaptureFrame``, or ``None`` if the buffer
            is empty.
        """
        if not self._buffer:
            return None
        return self._buffer[-1]

    def get_buffer_frames(self) -> list[CaptureFrame]:
        """Return all frames currently in the ring buffer.

        Frames are ordered oldest-first, newest-last.

        Returns:
            A list of ``CaptureFrame`` objects.
        """
        return list(self._buffer)

    @property
    def buffer_size(self) -> int:
        """Current number of frames in the ring buffer."""
        return len(self._buffer)

    @property
    def buffer_capacity(self) -> int:
        """Maximum number of frames the ring buffer can hold."""
        maxlen = self._buffer.maxlen
        # deque.maxlen is None when unbounded; treat as 0 capacity.
        return maxlen if maxlen is not None else 0

    def clear_buffer(self) -> None:
        """Remove all frames from the ring buffer."""
        self._buffer.clear()

    # ------------------------------------------------------------------
    # Frame differencing (Tier 0)
    # ------------------------------------------------------------------

    def compute_diff(
        self,
        frame_a: CaptureFrame,
        frame_b: CaptureFrame,
    ) -> DiffResult:
        """Compute the Tier 0 frame difference between two frames.

        Processing steps:

        1. Convert both images to grayscale.
        2. Compute the absolute pixel-wise difference.
        3. Threshold the diff at ``_DIFF_PIXEL_THRESHOLD`` to produce
           a binary mask of changed pixels.
        4. Calculate ``changed_percent`` as the ratio of changed
           pixels to total pixels, scaled to 0 -- 100.
        5. Find external contours in the binary mask and derive
           bounding rectangles for each.
        6. Classify the tier recommendation:

           * ``0`` if ``changed_percent < diff_threshold_percent``
           * ``2`` if ``changed_percent >= tier2_threshold_percent``
           * ``1`` otherwise

        Args:
            frame_a: The earlier (reference) frame.
            frame_b: The later (current) frame.

        Returns:
            A ``DiffResult`` summarising the change.
        """
        gray_a = cv2.cvtColor(frame_a.image, cv2.COLOR_BGR2GRAY)
        gray_b = cv2.cvtColor(frame_b.image, cv2.COLOR_BGR2GRAY)

        diff = cv2.absdiff(gray_a, gray_b)

        _, thresh = cv2.threshold(diff, _DIFF_PIXEL_THRESHOLD, 255, cv2.THRESH_BINARY)

        total_pixels = thresh.shape[0] * thresh.shape[1]
        changed_pixels = int(cv2.countNonZero(thresh))
        changed_percent = (changed_pixels / total_pixels) * 100.0

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        changed_regions: list[tuple[int, int, int, int]] = [cv2.boundingRect(c) for c in contours]

        tier = self._classify_tier(changed_percent)

        return DiffResult(
            changed_percent=changed_percent,
            changed_regions=changed_regions,
            tier_recommendation=tier,
        )

    def check_for_changes(self) -> DiffResult | None:
        """Compare the two most recent frames in the buffer.

        Convenience wrapper around ``compute_diff`` that operates
        on the ring buffer contents directly.

        Returns:
            A ``DiffResult`` describing the change between the
            last two buffered frames, or ``None`` if fewer than
            two frames are available.
        """
        if len(self._buffer) < 2:
            return None
        frame_a = self._buffer[-2]
        frame_b = self._buffer[-1]
        return self.compute_diff(frame_a, frame_b)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify_tier(self, changed_percent: float) -> int:
        """Map a changed-pixel percentage to an analysis tier.

        Args:
            changed_percent: Percentage of pixels that differ
                between the two compared frames (0 -- 100).

        Returns:
            ``0`` for no action, ``1`` for local region update,
            ``2`` for full API rebuild.
        """
        if changed_percent < self._settings.diff_threshold_percent:
            return 0
        if changed_percent >= self._settings.tier2_threshold_percent:
            return 2
        return 1
