"""Session recording module for the CIU Agent replay system.

The ``ReplayBuffer`` captures frames, spatial events, and director actions
into structured session directories on disk.  It is fully modular: it
receives ``Settings`` through its constructor and works exclusively with
plain data (numpy arrays, dataclasses).  It never imports or depends on
``CaptureEngine`` or any other core component at runtime.

Session directory layout::

    sessions/session_YYYYMMDD_HHMMSS/
        frames/          # PNG frames (when save_frames_as_png is True)
            000001.png
            ...
        cursor.jsonl     # One JSON object per cursor sample
        events.jsonl     # One serialised SpatialEvent per line
        actions.jsonl    # One serialised Action per line
        metadata.json    # SessionMetadata as JSON

Typical usage::

    from ciu_agent.config.settings import get_default_settings
    from ciu_agent.core.replay_buffer import ReplayBuffer

    buf = ReplayBuffer(get_default_settings())
    sid = buf.start_session(task_description="demo")
    # ... record frames, events, actions ...
    session_dir = buf.stop_session()
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from ciu_agent.config.settings import Settings
from ciu_agent.models.actions import Action
from ciu_agent.models.events import SpatialEvent

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CursorSample:
    """A single cursor-position sample tied to a frame.

    Attributes:
        x: Horizontal screen coordinate.
        y: Vertical screen coordinate.
        timestamp: Unix timestamp when the sample was taken.
        frame: Frame number this sample corresponds to.
    """

    x: int
    y: int
    timestamp: float
    frame: int


@dataclass
class SessionMetadata:
    """Metadata for a recorded session.

    Attributes:
        session_id: Unique identifier for this session.
        start_time: Unix timestamp when the session started.
        end_time: Unix timestamp when the session stopped.
        task_description: Human-readable description of the session goal.
        frame_count: Total number of frames recorded.
        event_count: Total number of spatial events recorded.
        action_count: Total number of director actions recorded.
        screen_width: Width of the captured screen in pixels.
        screen_height: Height of the captured screen in pixels.
    """

    session_id: str
    start_time: float
    end_time: float = 0.0
    task_description: str = ""
    frame_count: int = 0
    event_count: int = 0
    action_count: int = 0
    screen_width: int = 0
    screen_height: int = 0


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _enum_safe_dict(obj: Any) -> dict[str, Any]:
    """Convert a dataclass to a dict, replacing Enum values with names.

    Uses ``dataclasses.asdict`` and then walks the resulting dict to
    swap any ``Enum`` member for its ``.name`` string.  This keeps the
    JSONL output human-readable and safe for round-tripping.

    Args:
        obj: A dataclass instance to serialise.

    Returns:
        A plain dictionary with all Enum values replaced by their
        ``.name`` strings.
    """
    raw = asdict(obj)
    return _walk_enums(raw)


def _walk_enums(data: Any) -> Any:
    """Recursively replace Enum members with their name strings.

    Args:
        data: Arbitrary nested structure (dict, list, or scalar).

    Returns:
        The same structure with every ``Enum`` replaced by its
        ``.name`` attribute.
    """
    if isinstance(data, dict):
        return {k: _walk_enums(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_walk_enums(item) for item in data]
    if isinstance(data, tuple):
        return [_walk_enums(item) for item in data]
    if isinstance(data, Enum):
        return data.name
    return data


# ---------------------------------------------------------------------------
# ReplayBuffer
# ---------------------------------------------------------------------------


class ReplayBuffer:
    """Records frames, events, and actions into structured sessions.

    The buffer holds data in memory while a session is active and
    flushes everything to disk when ``stop_session`` is called.  Frame
    images are optionally written as PNGs during recording to avoid
    accumulating large numpy arrays in RAM.

    Args:
        settings: Injected application settings that control
            recording behaviour (``recording_enabled``,
            ``session_dir``, ``save_frames_as_png``).
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise with injected settings.

        Args:
            settings: Application-wide configuration.
        """
        self._settings: Settings = settings
        self._cursor_log: list[CursorSample] = []
        self._events: list[SpatialEvent] = []
        self._actions: list[Action] = []
        self._metadata: SessionMetadata | None = None
        self._session_dir: Path | None = None

    # -- Session lifecycle ---------------------------------------------------

    def start_session(
        self,
        session_id: str = "",
        task_description: str = "",
        screen_size: tuple[int, int] = (0, 0),
    ) -> str:
        """Start a new recording session.

        Creates the session directory on disk (including a ``frames/``
        sub-directory when ``save_frames_as_png`` is enabled) and
        resets all in-memory buffers.

        Args:
            session_id: Optional identifier.  When empty, one is
                generated from the current UTC timestamp in the format
                ``session_YYYYMMDD_HHMMSS``.
            task_description: Free-text description of what this
                session is intended to accomplish.
            screen_size: ``(width, height)`` of the screen being
                captured.

        Returns:
            The session identifier string.

        Raises:
            RuntimeError: If a session is already in progress.
        """
        if self._metadata is not None:
            raise RuntimeError(
                "A session is already in progress.  Call stop_session() before starting a new one."
            )

        if not session_id:
            now = datetime.now(tz=timezone.utc)
            session_id = now.strftime("session_%Y%m%d_%H%M%S")

        width, height = screen_size

        self._metadata = SessionMetadata(
            session_id=session_id,
            start_time=time.time(),
            task_description=task_description,
            screen_width=width,
            screen_height=height,
        )

        # Resolve session directory under the configured root.
        base = Path(self._settings.session_dir)
        self._session_dir = base / session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)

        if self._settings.save_frames_as_png:
            (self._session_dir / "frames").mkdir(exist_ok=True)

        # Reset in-memory buffers.
        self._cursor_log = []
        self._events = []
        self._actions = []

        return session_id

    def record_frame(
        self,
        image: NDArray[np.uint8],
        cursor_x: int,
        cursor_y: int,
        timestamp: float,
        frame_number: int,
    ) -> None:
        """Record a single frame with its cursor position.

        The cursor position is always appended to the in-memory log.
        If ``save_frames_as_png`` is enabled in settings, the frame
        image is also written to the ``frames/`` sub-directory as a
        PNG with a six-digit zero-padded filename.

        Args:
            image: The captured screen image as a numpy array
                (height, width, channels), dtype ``uint8``.
            cursor_x: Horizontal cursor coordinate.
            cursor_y: Vertical cursor coordinate.
            timestamp: Unix timestamp of the capture.
            frame_number: Monotonically increasing frame index.

        Raises:
            RuntimeError: If no session is currently active.
        """
        if self._metadata is None or self._session_dir is None:
            raise RuntimeError("No active session.  Call start_session() first.")

        self._cursor_log.append(
            CursorSample(
                x=cursor_x,
                y=cursor_y,
                timestamp=timestamp,
                frame=frame_number,
            )
        )
        self._metadata.frame_count += 1

        if self._settings.save_frames_as_png:
            filename = f"{frame_number:06d}.png"
            frame_path = self._session_dir / "frames" / filename
            cv2.imwrite(str(frame_path), image)

    def record_event(self, event: SpatialEvent) -> None:
        """Record a spatial event.

        The event is buffered in memory and will be flushed to
        ``events.jsonl`` when ``stop_session`` is called.

        Args:
            event: The spatial event to record.

        Raises:
            RuntimeError: If no session is currently active.
        """
        if self._metadata is None:
            raise RuntimeError("No active session.  Call start_session() first.")
        self._events.append(event)
        self._metadata.event_count += 1

    def record_action(self, action: Action) -> None:
        """Record a director action.

        The action is buffered in memory and will be flushed to
        ``actions.jsonl`` when ``stop_session`` is called.

        Args:
            action: The action to record.

        Raises:
            RuntimeError: If no session is currently active.
        """
        if self._metadata is None:
            raise RuntimeError("No active session.  Call start_session() first.")
        self._actions.append(action)
        self._metadata.action_count += 1

    def stop_session(self) -> Path:
        """Stop recording and finalise the session.

        Writes all buffered data to disk inside the session directory:

        - ``cursor.jsonl`` -- one JSON line per cursor sample.
        - ``events.jsonl`` -- one JSON line per spatial event.
        - ``actions.jsonl`` -- one JSON line per director action.
        - ``metadata.json`` -- full session metadata.

        Returns:
            Path to the session directory.

        Raises:
            RuntimeError: If no session is currently active.
        """
        if self._metadata is None or self._session_dir is None:
            raise RuntimeError("No active session.  Call start_session() first.")

        self._metadata.end_time = time.time()

        # -- Cursor log ------------------------------------------------------
        cursor_path = self._session_dir / "cursor.jsonl"
        with cursor_path.open("w", encoding="utf-8") as fh:
            for sample in self._cursor_log:
                line = json.dumps(asdict(sample), ensure_ascii=False)
                fh.write(line + "\n")

        # -- Events ----------------------------------------------------------
        events_path = self._session_dir / "events.jsonl"
        with events_path.open("w", encoding="utf-8") as fh:
            for event in self._events:
                line = json.dumps(_enum_safe_dict(event), ensure_ascii=False)
                fh.write(line + "\n")

        # -- Actions ---------------------------------------------------------
        actions_path = self._session_dir / "actions.jsonl"
        with actions_path.open("w", encoding="utf-8") as fh:
            for action in self._actions:
                line = json.dumps(_enum_safe_dict(action), ensure_ascii=False)
                fh.write(line + "\n")

        # -- Metadata --------------------------------------------------------
        meta_path = self._session_dir / "metadata.json"
        with meta_path.open("w", encoding="utf-8") as fh:
            json.dump(
                asdict(self._metadata),
                fh,
                indent=2,
                ensure_ascii=False,
            )
            fh.write("\n")

        session_dir = self._session_dir

        # Clear internal state so a new session can start.
        self._cursor_log = []
        self._events = []
        self._actions = []
        self._metadata = None
        self._session_dir = None

        return session_dir

    # -- Replay / inspection -------------------------------------------------

    def load_session(self, session_dir: Path) -> SessionMetadata:
        """Load session metadata from a saved session directory.

        Args:
            session_dir: Path to a previously saved session directory
                that contains a ``metadata.json`` file.

        Returns:
            A ``SessionMetadata`` instance populated from the file.

        Raises:
            FileNotFoundError: If ``metadata.json`` does not exist
                inside *session_dir*.
        """
        meta_path = session_dir / "metadata.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"No metadata.json found in {session_dir}")

        with meta_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)

        return SessionMetadata(**raw)

    # -- Properties ----------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """Whether a session is currently being recorded."""
        return self._metadata is not None

    @property
    def session_path(self) -> Path | None:
        """Path to the current session directory, or None."""
        return self._session_dir
