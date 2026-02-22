"""Tests for CIU Agent configuration and settings.

Covers default construction, serialisation round-trip, immutability,
field types, and forward-compatible dict loading.
"""

from __future__ import annotations

import pytest

from ciu_agent.config.settings import Settings, get_default_settings


class TestGetDefaultSettings:
    """Tests for the get_default_settings factory function."""

    def test_returns_settings_instance(self) -> None:
        """get_default_settings must return a Settings object."""
        s = get_default_settings()
        assert isinstance(s, Settings)

    def test_target_fps_default(self) -> None:
        """Default target_fps is 15."""
        assert get_default_settings().target_fps == 15

    def test_max_fps_default(self) -> None:
        """Default max_fps is 30."""
        assert get_default_settings().max_fps == 30

    def test_ring_buffer_seconds_default(self) -> None:
        """Default ring_buffer_seconds is 5.0."""
        assert get_default_settings().ring_buffer_seconds == 5.0

    def test_diff_threshold_percent_default(self) -> None:
        """Default diff_threshold_percent is 0.5."""
        assert get_default_settings().diff_threshold_percent == 0.5

    def test_tier2_threshold_percent_default(self) -> None:
        """Default tier2_threshold_percent is 30.0."""
        assert get_default_settings().tier2_threshold_percent == 30.0

    def test_stability_wait_ms_default(self) -> None:
        """Default stability_wait_ms is 500."""
        assert get_default_settings().stability_wait_ms == 500

    def test_min_zone_confidence_default(self) -> None:
        """Default min_zone_confidence is 0.7."""
        assert get_default_settings().min_zone_confidence == 0.7

    def test_zone_expiry_seconds_default(self) -> None:
        """Default zone_expiry_seconds is 60.0."""
        assert get_default_settings().zone_expiry_seconds == 60.0

    def test_hover_threshold_ms_default(self) -> None:
        """Default hover_threshold_ms is 300."""
        assert get_default_settings().hover_threshold_ms == 300

    def test_motion_speed_default(self) -> None:
        """Default motion_speed_pixels_per_sec is 1500.0."""
        assert get_default_settings().motion_speed_pixels_per_sec == 1500.0

    def test_api_timeout_vision_seconds_default(self) -> None:
        """Default api_timeout_vision_seconds is 30.0."""
        assert get_default_settings().api_timeout_vision_seconds == 30.0

    def test_api_timeout_text_seconds_default(self) -> None:
        """Default api_timeout_text_seconds is 15.0."""
        assert get_default_settings().api_timeout_text_seconds == 15.0

    def test_api_max_retries_default(self) -> None:
        """Default api_max_retries is 3."""
        assert get_default_settings().api_max_retries == 3

    def test_api_backoff_base_seconds_default(self) -> None:
        """Default api_backoff_base_seconds is 2.0."""
        assert get_default_settings().api_backoff_base_seconds == 2.0

    def test_recording_enabled_default(self) -> None:
        """Default recording_enabled is True."""
        assert get_default_settings().recording_enabled is True

    def test_session_dir_default(self) -> None:
        """Default session_dir is 'sessions'."""
        assert get_default_settings().session_dir == "sessions"

    def test_save_frames_as_png_default(self) -> None:
        """Default save_frames_as_png is True."""
        assert get_default_settings().save_frames_as_png is True

    def test_compress_video_default(self) -> None:
        """Default compress_video is True."""
        assert get_default_settings().compress_video is True

    def test_platform_name_default(self) -> None:
        """Default platform_name is empty (auto-detect)."""
        assert get_default_settings().platform_name == ""


class TestSettingsToDict:
    """Tests for Settings.to_dict serialisation."""

    def test_returns_dict(self) -> None:
        """to_dict must return a plain dict."""
        d = get_default_settings().to_dict()
        assert isinstance(d, dict)

    def test_contains_all_fields(self) -> None:
        """The dict must have one key per Settings field."""
        s = get_default_settings()
        d = s.to_dict()
        from dataclasses import fields as dc_fields

        expected_keys = {f.name for f in dc_fields(Settings)}
        assert set(d.keys()) == expected_keys

    def test_values_match_attributes(self) -> None:
        """Dict values must equal the corresponding attributes."""
        s = get_default_settings()
        d = s.to_dict()
        assert d["target_fps"] == s.target_fps
        assert d["max_fps"] == s.max_fps
        assert d["ring_buffer_seconds"] == s.ring_buffer_seconds
        assert d["diff_threshold_percent"] == s.diff_threshold_percent
        assert d["recording_enabled"] == s.recording_enabled
        assert d["platform_name"] == s.platform_name


class TestSettingsFromDict:
    """Tests for Settings.from_dict deserialisation."""

    def test_round_trip(self) -> None:
        """from_dict(to_dict()) produces an identical Settings."""
        original = get_default_settings()
        rebuilt = Settings.from_dict(original.to_dict())
        assert rebuilt == original

    def test_round_trip_with_overrides(self) -> None:
        """Custom values survive a round-trip through dict form."""
        custom = Settings(target_fps=60, max_fps=120, platform_name="linux")
        rebuilt = Settings.from_dict(custom.to_dict())
        assert rebuilt.target_fps == 60
        assert rebuilt.max_fps == 120
        assert rebuilt.platform_name == "linux"

    def test_partial_dict_fills_defaults(self) -> None:
        """A dict with only some keys produces defaults for the rest."""
        s = Settings.from_dict({"target_fps": 10})
        assert s.target_fps == 10
        assert s.max_fps == 30  # default
        assert s.platform_name == ""  # default

    def test_empty_dict_gives_defaults(self) -> None:
        """An empty dict produces a fully-default Settings."""
        s = Settings.from_dict({})
        assert s == get_default_settings()

    def test_ignores_unknown_keys(self) -> None:
        """Unknown keys in the dict are silently discarded."""
        data = {
            "target_fps": 20,
            "nonexistent_option": True,
            "another_fake": "abc",
        }
        s = Settings.from_dict(data)
        assert s.target_fps == 20
        assert not hasattr(s, "nonexistent_option")
        assert not hasattr(s, "another_fake")

    def test_ignores_unknown_keys_without_side_effects(self) -> None:
        """Unknown keys do not interfere with known field defaults."""
        s = Settings.from_dict({"bogus_key": 999})
        assert s == get_default_settings()


class TestSettingsFrozen:
    """Tests for the immutability guarantee of Settings."""

    def test_cannot_set_attribute(self) -> None:
        """Assigning to any field must raise an error."""
        s = get_default_settings()
        with pytest.raises(AttributeError):
            s.target_fps = 60  # type: ignore[misc]

    def test_cannot_set_string_attribute(self) -> None:
        """Assigning to a string field must also raise."""
        s = get_default_settings()
        with pytest.raises(AttributeError):
            s.platform_name = "linux"  # type: ignore[misc]

    def test_cannot_set_bool_attribute(self) -> None:
        """Assigning to a bool field must also raise."""
        s = get_default_settings()
        with pytest.raises(AttributeError):
            s.recording_enabled = False  # type: ignore[misc]

    def test_cannot_delete_attribute(self) -> None:
        """Deleting a field must raise an error."""
        s = get_default_settings()
        with pytest.raises(AttributeError):
            del s.target_fps  # type: ignore[misc]


class TestSettingsFieldTypes:
    """Tests that every Settings field has the correct Python type."""

    def test_int_fields(self) -> None:
        """Integer fields must be int, not float or str."""
        s = get_default_settings()
        int_fields = [
            "target_fps",
            "max_fps",
            "stability_wait_ms",
            "hover_threshold_ms",
            "api_max_retries",
        ]
        for name in int_fields:
            value = getattr(s, name)
            assert isinstance(value, int), f"{name} should be int, got {type(value).__name__}"

    def test_float_fields(self) -> None:
        """Float fields must be float."""
        s = get_default_settings()
        float_fields = [
            "ring_buffer_seconds",
            "diff_threshold_percent",
            "tier2_threshold_percent",
            "min_zone_confidence",
            "zone_expiry_seconds",
            "motion_speed_pixels_per_sec",
            "api_timeout_vision_seconds",
            "api_timeout_text_seconds",
            "api_backoff_base_seconds",
        ]
        for name in float_fields:
            value = getattr(s, name)
            assert isinstance(value, float), f"{name} should be float, got {type(value).__name__}"

    def test_bool_fields(self) -> None:
        """Boolean fields must be bool, not int."""
        s = get_default_settings()
        bool_fields = [
            "recording_enabled",
            "save_frames_as_png",
            "compress_video",
        ]
        for name in bool_fields:
            value = getattr(s, name)
            assert isinstance(value, bool), f"{name} should be bool, got {type(value).__name__}"

    def test_str_fields(self) -> None:
        """String fields must be str."""
        s = get_default_settings()
        str_fields = ["session_dir", "platform_name"]
        for name in str_fields:
            value = getattr(s, name)
            assert isinstance(value, str), f"{name} should be str, got {type(value).__name__}"
