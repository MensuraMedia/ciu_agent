"""Unit tests for the CIU Agent replay buffer.

Tests cover SessionMetadata construction, ReplayBuffer lifecycle (start, record,
stop), file output verification, and session reloading.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from ciu_agent.config.settings import get_default_settings
from ciu_agent.core.replay_buffer import ReplayBuffer, SessionMetadata
from ciu_agent.models.actions import Action, ActionStatus, ActionType
from ciu_agent.models.events import SpatialEvent, SpatialEventType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path):
    """Settings with session_dir pointing to a temp directory."""
    return replace(get_default_settings(), session_dir=str(tmp_path))


@pytest.fixture
def settings_no_png(tmp_path: Path):
    """Settings with save_frames_as_png disabled."""
    return replace(
        get_default_settings(),
        session_dir=str(tmp_path),
        save_frames_as_png=False,
    )


@pytest.fixture
def buf(settings):
    """A fresh ReplayBuffer backed by a temporary session directory."""
    return ReplayBuffer(settings)


@pytest.fixture
def buf_no_png(settings_no_png):
    """A ReplayBuffer that does not save frame PNGs."""
    return ReplayBuffer(settings_no_png)


@pytest.fixture
def test_frame() -> np.ndarray:
    """A minimal 100x100 BGR test frame."""
    return np.zeros((100, 100, 3), dtype=np.uint8)


@pytest.fixture
def sample_event() -> SpatialEvent:
    """A representative SpatialEvent for recording tests."""
    return SpatialEvent(
        type=SpatialEventType.ZONE_CLICK,
        zone_id="btn_ok",
        timestamp=1000.0,
        position=(200, 300),
        data={"button": "left"},
    )


@pytest.fixture
def sample_action() -> Action:
    """A representative Action for recording tests."""
    return Action(
        type=ActionType.CLICK,
        target_zone_id="btn_ok",
        status=ActionStatus.COMPLETED,
        parameters={"button": "left"},
        timestamp=1000.0,
        result="clicked",
    )


# ---------------------------------------------------------------------------
# SessionMetadata tests
# ---------------------------------------------------------------------------


class TestSessionMetadata:
    """Tests for the SessionMetadata dataclass."""

    def test_construction_defaults_populated(self) -> None:
        """SessionMetadata with only required fields uses sane defaults."""
        meta = SessionMetadata(
            session_id="test_001",
            start_time=1000.0,
        )
        assert meta.end_time == 0.0
        assert meta.task_description == ""
        assert meta.frame_count == 0
        assert meta.event_count == 0
        assert meta.action_count == 0
        assert meta.screen_width == 0
        assert meta.screen_height == 0

    def test_fields_have_correct_types(self) -> None:
        """All fields resolve to the expected Python types."""
        meta = SessionMetadata(
            session_id="test_002",
            start_time=1000.5,
            end_time=2000.5,
            task_description="demo",
            frame_count=10,
            event_count=3,
            action_count=2,
            screen_width=1920,
            screen_height=1080,
        )
        assert isinstance(meta.session_id, str)
        assert isinstance(meta.start_time, float)
        assert isinstance(meta.end_time, float)
        assert isinstance(meta.task_description, str)
        assert isinstance(meta.frame_count, int)
        assert isinstance(meta.event_count, int)
        assert isinstance(meta.action_count, int)
        assert isinstance(meta.screen_width, int)
        assert isinstance(meta.screen_height, int)


# ---------------------------------------------------------------------------
# ReplayBuffer lifecycle tests
# ---------------------------------------------------------------------------


class TestReplayBufferLifecycle:
    """Tests for start_session / stop_session lifecycle."""

    def test_is_recording_initially_false(self, buf: ReplayBuffer) -> None:
        """A fresh buffer reports is_recording as False."""
        assert buf.is_recording is False

    def test_session_path_initially_none(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """A fresh buffer has no session_path."""
        assert buf.session_path is None

    def test_start_session_returns_session_id(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """start_session returns a non-empty string identifier."""
        sid = buf.start_session()
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_start_session_creates_directory(
        self,
        buf: ReplayBuffer,
        settings,
    ) -> None:
        """start_session creates the session directory on disk."""
        sid = buf.start_session(session_id="my_session")
        expected = Path(settings.session_dir) / sid
        assert expected.is_dir()

    def test_start_session_auto_id_format(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """Auto-generated session IDs follow session_YYYYMMDD_HHMMSS."""
        sid = buf.start_session()
        pattern = r"^session_\d{8}_\d{6}$"
        assert re.match(pattern, sid), f"Auto-generated ID '{sid}' does not match expected format"

    def test_start_session_custom_id_used(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """When a custom session_id is supplied, it is used verbatim."""
        sid = buf.start_session(session_id="custom_42")
        assert sid == "custom_42"

    def test_double_start_raises_runtime_error(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """Starting a session while one is active raises RuntimeError."""
        buf.start_session(session_id="first")
        with pytest.raises(RuntimeError):
            buf.start_session(session_id="second")

    def test_after_start_is_recording_true(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """is_recording becomes True after start_session."""
        buf.start_session(session_id="rec")
        assert buf.is_recording is True


# ---------------------------------------------------------------------------
# Recording tests
# ---------------------------------------------------------------------------


class TestRecording:
    """Tests for record_frame, record_event, and record_action."""

    def test_record_frame_increments_frame_count(
        self,
        buf: ReplayBuffer,
        test_frame: np.ndarray,
    ) -> None:
        """Each record_frame call increments the internal frame count."""
        buf.start_session(session_id="frames")
        buf.record_frame(test_frame, 10, 20, 1000.0, 1)
        buf.record_frame(test_frame, 30, 40, 1001.0, 2)
        session_dir = buf.stop_session()

        meta_path = session_dir / "metadata.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["frame_count"] == 2

    def test_record_frame_saves_png_when_enabled(
        self,
        buf: ReplayBuffer,
        test_frame: np.ndarray,
    ) -> None:
        """When save_frames_as_png is True, PNGs appear in frames/."""
        buf.start_session(session_id="png_test")
        buf.record_frame(test_frame, 0, 0, 1000.0, 1)
        buf.record_frame(test_frame, 0, 0, 1001.0, 2)

        frames_dir = buf.session_path / "frames"
        assert (frames_dir / "000001.png").exists()
        assert (frames_dir / "000002.png").exists()

        buf.stop_session()

    def test_record_frame_no_png_when_disabled(
        self,
        buf_no_png: ReplayBuffer,
        test_frame: np.ndarray,
    ) -> None:
        """When save_frames_as_png is False, no frames/ directory."""
        buf_no_png.start_session(session_id="nopng")
        buf_no_png.record_frame(test_frame, 0, 0, 1000.0, 1)

        session_dir = buf_no_png.session_path
        assert not (session_dir / "frames").exists()

        buf_no_png.stop_session()

    def test_record_event_buffers_events(
        self,
        buf: ReplayBuffer,
        sample_event: SpatialEvent,
    ) -> None:
        """record_event accumulates events that appear in stop output."""
        buf.start_session(session_id="evt")
        buf.record_event(sample_event)
        buf.record_event(sample_event)
        session_dir = buf.stop_session()

        events_path = session_dir / "events.jsonl"
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_record_action_buffers_actions(
        self,
        buf: ReplayBuffer,
        sample_action: Action,
    ) -> None:
        """record_action accumulates actions written at stop."""
        buf.start_session(session_id="act")
        buf.record_action(sample_action)
        session_dir = buf.stop_session()

        actions_path = session_dir / "actions.jsonl"
        lines = actions_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# Stop session tests
# ---------------------------------------------------------------------------


class TestStopSession:
    """Tests for the stop_session output and state reset."""

    def test_stop_writes_cursor_jsonl(
        self,
        buf: ReplayBuffer,
        test_frame: np.ndarray,
    ) -> None:
        """stop_session creates cursor.jsonl."""
        buf.start_session(session_id="cur")
        buf.record_frame(test_frame, 5, 10, 1000.0, 1)
        session_dir = buf.stop_session()
        assert (session_dir / "cursor.jsonl").exists()

    def test_stop_writes_events_jsonl(
        self,
        buf: ReplayBuffer,
        sample_event: SpatialEvent,
    ) -> None:
        """stop_session creates events.jsonl."""
        buf.start_session(session_id="ev")
        buf.record_event(sample_event)
        session_dir = buf.stop_session()
        assert (session_dir / "events.jsonl").exists()

    def test_stop_writes_actions_jsonl(
        self,
        buf: ReplayBuffer,
        sample_action: Action,
    ) -> None:
        """stop_session creates actions.jsonl."""
        buf.start_session(session_id="ac")
        buf.record_action(sample_action)
        session_dir = buf.stop_session()
        assert (session_dir / "actions.jsonl").exists()

    def test_stop_writes_metadata_json(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """stop_session creates metadata.json."""
        buf.start_session(session_id="meta")
        session_dir = buf.stop_session()
        assert (session_dir / "metadata.json").exists()

    def test_after_stop_is_recording_false(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """is_recording resets to False after stop_session."""
        buf.start_session(session_id="s")
        buf.stop_session()
        assert buf.is_recording is False

    def test_stop_returns_session_directory_path(
        self,
        buf: ReplayBuffer,
        settings,
    ) -> None:
        """stop_session returns the Path to the session directory."""
        buf.start_session(session_id="retpath")
        result = buf.stop_session()
        expected = Path(settings.session_dir) / "retpath"
        assert result == expected
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# Load session tests
# ---------------------------------------------------------------------------


class TestLoadSession:
    """Tests for load_session round-trip metadata reading."""

    def test_load_session_reads_metadata_correctly(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """Loaded metadata preserves the original session_id and task."""
        buf.start_session(
            session_id="load_test",
            task_description="Integration test",
            screen_size=(1920, 1080),
        )
        session_dir = buf.stop_session()

        loaded = buf.load_session(session_dir)
        assert loaded.session_id == "load_test"
        assert loaded.task_description == "Integration test"
        assert loaded.screen_width == 1920
        assert loaded.screen_height == 1080

    def test_loaded_metadata_counts_correct(
        self,
        buf: ReplayBuffer,
        test_frame: np.ndarray,
        sample_event: SpatialEvent,
        sample_action: Action,
    ) -> None:
        """Loaded metadata reports accurate frame, event, action counts."""
        buf.start_session(session_id="counts")

        buf.record_frame(test_frame, 0, 0, 1.0, 1)
        buf.record_frame(test_frame, 0, 0, 2.0, 2)
        buf.record_frame(test_frame, 0, 0, 3.0, 3)

        buf.record_event(sample_event)
        buf.record_event(sample_event)

        buf.record_action(sample_action)

        session_dir = buf.stop_session()

        loaded = buf.load_session(session_dir)
        assert loaded.frame_count == 3
        assert loaded.event_count == 2
        assert loaded.action_count == 1


# ---------------------------------------------------------------------------
# JSONL content tests
# ---------------------------------------------------------------------------


class TestJsonlContent:
    """Tests that verify the actual JSON content of output files."""

    def test_cursor_jsonl_has_correct_keys(
        self,
        buf: ReplayBuffer,
        test_frame: np.ndarray,
    ) -> None:
        """Each line in cursor.jsonl has x, y, timestamp, frame keys."""
        buf.start_session(session_id="ckeys")
        buf.record_frame(test_frame, 42, 99, 1234.5, 7)
        session_dir = buf.stop_session()

        cursor_path = session_dir / "cursor.jsonl"
        lines = cursor_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

        obj = json.loads(lines[0])
        assert obj["x"] == 42
        assert obj["y"] == 99
        assert obj["timestamp"] == 1234.5
        assert obj["frame"] == 7

    def test_cursor_jsonl_multiple_samples(
        self,
        buf: ReplayBuffer,
        test_frame: np.ndarray,
    ) -> None:
        """Multiple frames produce multiple cursor.jsonl lines."""
        buf.start_session(session_id="cmulti")
        buf.record_frame(test_frame, 1, 2, 100.0, 1)
        buf.record_frame(test_frame, 3, 4, 101.0, 2)
        buf.record_frame(test_frame, 5, 6, 102.0, 3)
        session_dir = buf.stop_session()

        cursor_path = session_dir / "cursor.jsonl"
        lines = cursor_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

        for i, line in enumerate(lines, start=1):
            obj = json.loads(line)
            assert set(obj.keys()) == {"x", "y", "timestamp", "frame"}
            assert obj["frame"] == i

    def test_events_jsonl_uses_enum_names(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """Events JSONL serialises enum fields as names, not values."""
        event = SpatialEvent(
            type=SpatialEventType.ZONE_ENTER,
            zone_id="sidebar",
            timestamp=500.0,
            position=(10, 20),
        )
        buf.start_session(session_id="enames")
        buf.record_event(event)
        session_dir = buf.stop_session()

        events_path = session_dir / "events.jsonl"
        lines = events_path.read_text(encoding="utf-8").strip().split("\n")
        obj = json.loads(lines[0])

        # Must be the enum *name* (e.g. "ZONE_ENTER"), not the value
        # (e.g. "zone_enter").
        assert obj["type"] == "ZONE_ENTER"
        assert obj["zone_id"] == "sidebar"
        assert obj["position"] == [10, 20]

    def test_actions_jsonl_uses_enum_names(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """Actions JSONL serialises enum fields as names, not values."""
        action = Action(
            type=ActionType.TYPE_TEXT,
            target_zone_id="input_field",
            status=ActionStatus.IN_PROGRESS,
            parameters={"text": "hello"},
            timestamp=600.0,
            result="",
        )
        buf.start_session(session_id="anames")
        buf.record_action(action)
        session_dir = buf.stop_session()

        actions_path = session_dir / "actions.jsonl"
        lines = actions_path.read_text(encoding="utf-8").strip().split("\n")
        obj = json.loads(lines[0])

        assert obj["type"] == "TYPE_TEXT"
        assert obj["status"] == "IN_PROGRESS"
        assert obj["target_zone_id"] == "input_field"
        assert obj["parameters"] == {"text": "hello"}

    def test_metadata_json_has_end_time(
        self,
        buf: ReplayBuffer,
    ) -> None:
        """metadata.json records a non-zero end_time after stop."""
        buf.start_session(session_id="endtime")
        session_dir = buf.stop_session()

        meta_path = session_dir / "metadata.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["end_time"] > 0.0
        assert meta["end_time"] >= meta["start_time"]
