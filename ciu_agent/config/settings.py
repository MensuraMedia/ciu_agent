"""Configuration defaults for the CIU Agent system.

Provides the ``Settings`` dataclass that holds every tunable parameter
for the capture engine, frame differencing, zone detection, brush
controller, API integration, replay buffer, and platform layer.

Typical usage::

    from ciu_agent.config.settings import get_default_settings

    settings = get_default_settings()
    print(settings.target_fps)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass(frozen=True)
class Settings:
    """Immutable configuration for the entire CIU Agent system.

    Each attribute group maps to one architectural component.  Values
    are intentionally conservative for Intel UHD-class hardware (CPU-only
    local compute, 2 GB shared VRAM).

    Attributes:
        target_fps: Target frame capture rate in frames per second.
        max_fps: Hard upper limit on capture rate.
        ring_buffer_seconds: Duration of the in-memory ring buffer that
            stores recent frames for replay and analysis.
        diff_threshold_percent: Minimum percentage of pixels that must
            change between frames before Tier 0 considers the frame
            "different" and forwards it for further analysis.
        tier2_threshold_percent: Percentage of changed pixels that
            triggers a full Tier 2 API rebuild of the canvas map.
        stability_wait_ms: Milliseconds to wait after the last detected
            change before treating the screen as stable (lets CSS
            animations and scrolling settle).
        min_zone_confidence: Minimum confidence score (0-1) required to
            register a new zone in the Canvas Mapper.
        zone_expiry_seconds: Seconds before an unconfirmed or stale
            zone is removed from the zone registry.
        hover_threshold_ms: Milliseconds the cursor must remain inside a
            zone before a hover event is emitted.
        motion_speed_pixels_per_sec: Default cursor movement speed used
            by the Brush Controller for smooth pointer travel.
        api_timeout_vision_seconds: HTTP timeout for vision (image)
            requests to the Claude API.
        api_timeout_text_seconds: HTTP timeout for text-only requests to
            the Claude API.
        api_max_retries: Maximum number of retry attempts for transient
            API failures.
        api_backoff_base_seconds: Base delay for exponential back-off
            between API retries.
        recording_enabled: Whether the replay buffer should persist
            session data to disk.
        session_dir: Directory (relative to the project root) where
            replay session data is stored.
        save_frames_as_png: When True, individual frames are saved as
            PNG images alongside the session metadata.
        compress_video: When True, completed sessions are compressed
            into a video file for compact storage.
        platform_name: Explicit platform override (``linux``,
            ``windows``, ``macos``).  Left empty for auto-detection.
    """

    # -- Capture engine -------------------------------------------------------
    target_fps: int = 15
    max_fps: int = 30
    ring_buffer_seconds: float = 5.0

    # -- Frame differencing (Tier 0) ------------------------------------------
    diff_threshold_percent: float = 0.5
    tier2_threshold_percent: float = 30.0
    stability_wait_ms: int = 500

    # -- Zone detection -------------------------------------------------------
    min_zone_confidence: float = 0.7
    zone_expiry_seconds: float = 60.0

    # -- Brush controller -----------------------------------------------------
    hover_threshold_ms: int = 300
    motion_speed_pixels_per_sec: float = 1500.0

    # -- API settings ---------------------------------------------------------
    api_timeout_vision_seconds: float = 30.0
    api_timeout_text_seconds: float = 15.0
    api_max_retries: int = 3
    api_backoff_base_seconds: float = 2.0

    # -- Replay buffer --------------------------------------------------------
    recording_enabled: bool = True
    session_dir: str = "sessions"
    save_frames_as_png: bool = True
    compress_video: bool = True

    # -- Platform -------------------------------------------------------------
    platform_name: str = ""

    # -- Factory & serialisation ----------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        """Create a ``Settings`` instance from a plain dictionary.

        Unknown keys are silently ignored so that forward-compatible
        config files do not break older agent versions.

        Args:
            data: Dictionary whose keys correspond to ``Settings``
                field names.  Only recognised keys are used; the rest
                are discarded.

        Returns:
            A new ``Settings`` instance populated from *data*, with
            defaults filling any missing keys.
        """
        known_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known_names}
        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the settings to a plain dictionary.

        Returns:
            A shallow dictionary mapping every field name to its
            current value.
        """
        return asdict(self)


def get_default_settings() -> Settings:
    """Return a ``Settings`` instance with all default values.

    This is the canonical way to obtain baseline configuration.  Call
    ``Settings.from_dict`` when you need to overlay user overrides on
    top of the defaults.

    Returns:
        A freshly constructed ``Settings`` with default values.
    """
    return Settings()
