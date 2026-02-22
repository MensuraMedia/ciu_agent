"""CLI replay viewer for CIU Agent recorded sessions.

Loads a session directory produced by ``ReplayBuffer`` and plays it back
in an OpenCV window with cursor overlay, event annotations, and frame
timing.  Also provides a text summary mode for headless or CI
environments.

Session directory layout (produced by ``ReplayBuffer``)::

    sessions/session_YYYYMMDD_HHMMSS/
        frames/          # PNG frames (when save_frames_as_png is True)
            000001.png
            ...
        cursor.jsonl     # One JSON object per cursor sample
        events.jsonl     # Spatial events serialised as JSON per line
        actions.jsonl    # Director actions serialised as JSON per line
        metadata.json    # SessionMetadata as JSON

Typical usage::

    python -m ciu_agent.replay_viewer -s sessions/session_20260222_143000
    python -m ciu_agent.replay_viewer -s sessions/session_20260222_143000 --summary-only
    python -m ciu_agent.replay_viewer -s sessions/session_20260222_143000 --speed 2.0
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """Holds all loaded data for a single recorded session.

    Attributes:
        metadata: Parsed contents of ``metadata.json``.
        cursor_samples: Cursor positions loaded from ``cursor.jsonl``.
        events: Spatial events loaded from ``events.jsonl``.
        actions: Director actions loaded from ``actions.jsonl``.
        frame_paths: Sorted paths to frame PNG files in ``frames/``.
        frame_count: Number of frames available on disk.
    """

    metadata: dict[str, Any]
    cursor_samples: list[dict[str, Any]]
    events: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    frame_paths: list[Path]
    frame_count: int = 0


# ---------------------------------------------------------------------------
# Session loader
# ---------------------------------------------------------------------------


class SessionLoader:
    """Loads a session directory into a ``Session`` instance.

    The loader reads each file independently and tolerates missing
    optional files (``cursor.jsonl``, ``events.jsonl``, ``actions.jsonl``,
    ``frames/``).  Only ``metadata.json`` is required.
    """

    def load(self, session_dir: str | Path) -> Session:
        """Load all session data from a directory on disk.

        Args:
            session_dir: Path to the session directory that contains
                at least a ``metadata.json`` file.

        Returns:
            A fully populated ``Session`` instance.

        Raises:
            FileNotFoundError: If *session_dir* does not exist or does
                not contain ``metadata.json``.
        """
        root = Path(session_dir)
        if not root.is_dir():
            raise FileNotFoundError(f"Session directory not found: {root}")

        metadata = self._load_metadata(root)
        cursor_samples = self._load_jsonl(root / "cursor.jsonl")
        events = self._load_jsonl(root / "events.jsonl")
        actions = self._load_jsonl(root / "actions.jsonl")
        frame_paths = self._discover_frames(root / "frames")

        return Session(
            metadata=metadata,
            cursor_samples=cursor_samples,
            events=events,
            actions=actions,
            frame_paths=frame_paths,
            frame_count=len(frame_paths),
        )

    def _load_metadata(self, root: Path) -> dict[str, Any]:
        """Read and parse ``metadata.json``.

        Args:
            root: Session directory path.

        Returns:
            Parsed JSON as a dictionary.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        meta_path = root / "metadata.json"
        if not meta_path.exists():
            raise FileNotFoundError(
                f"No metadata.json found in {root}"
            )
        with meta_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _load_jsonl(self, path: Path) -> list[dict[str, Any]]:
        """Read a JSONL file, returning one dict per line.

        Returns an empty list when the file does not exist or is empty.

        Args:
            path: Path to the ``.jsonl`` file.

        Returns:
            List of parsed JSON objects.
        """
        if not path.exists():
            return []
        results: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped:
                    results.append(json.loads(stripped))
        return results

    def _discover_frames(self, frames_dir: Path) -> list[Path]:
        """Find and sort frame PNGs in the ``frames/`` subdirectory.

        Frames are sorted lexicographically, which matches the
        zero-padded naming convention ``000001.png``, ``000002.png``, etc.

        Args:
            frames_dir: Path to the ``frames/`` subdirectory.

        Returns:
            Sorted list of paths, or an empty list if the directory
            does not exist.
        """
        if not frames_dir.is_dir():
            return []
        return sorted(frames_dir.glob("*.png"))


# ---------------------------------------------------------------------------
# Replay viewer
# ---------------------------------------------------------------------------


# Colour constants (BGR for OpenCV).
_CURSOR_COLOUR = (0, 255, 0)       # Green
_CURSOR_OUTLINE = (0, 200, 0)      # Darker green
_TEXT_COLOUR = (255, 255, 255)      # White
_TEXT_BG_COLOUR = (0, 0, 0)        # Black
_EVENT_ENTER_COLOUR = (255, 200, 0)  # Cyan-ish
_EVENT_EXIT_COLOUR = (0, 0, 255)   # Red
_EVENT_CLICK_COLOUR = (0, 255, 255)  # Yellow
_EVENT_LOST_COLOUR = (0, 0, 200)   # Dark red
_EVENT_DEFAULT_COLOUR = (200, 200, 200)  # Grey

_WINDOW_NAME = "CIU Agent Replay"
_FONT = cv2.FONT_HERSHEY_SIMPLEX
_FONT_SCALE = 0.5
_FONT_THICKNESS = 1


class ReplayViewer:
    """Plays back a recorded session in an OpenCV window.

    Supports continuous playback with adjustable speed, pause/resume,
    and single-frame stepping.

    Args:
        session: A loaded ``Session`` instance to replay.
    """

    def __init__(self, session: Session) -> None:
        """Store the session for playback.

        Args:
            session: The session data to replay.
        """
        self._session = session
        self._paused = False

    def play(self, speed: float = 1.0) -> None:
        """Play the session frames in an OpenCV window.

        Controls:
            - ``q``: Quit playback.
            - ``Space``: Toggle pause / resume.
            - ``Right arrow``: Step forward one frame (while paused).
            - ``Left arrow``: Step backward one frame (while paused).

        If the session has no frames on disk, prints a message and
        returns immediately.

        Args:
            speed: Playback speed multiplier.  Values greater than 1.0
                play faster; values less than 1.0 play slower.
        """
        if self._session.frame_count == 0:
            print("No frames found in session. Use --summary-only instead.")
            return

        # Build lookup structures.
        cursor_by_frame = self._build_cursor_index()
        events_by_frame = self._build_events_index()

        # Compute per-frame delay from metadata timestamps.
        base_delay_ms = self._compute_frame_delay_ms()
        if base_delay_ms <= 0:
            base_delay_ms = 67  # ~15 fps fallback

        frame_idx = 0

        try:
            while 0 <= frame_idx < self._session.frame_count:
                frame_path = self._session.frame_paths[frame_idx]
                image = cv2.imread(str(frame_path))
                if image is None:
                    print(f"Warning: could not read {frame_path}, skipping.")
                    frame_idx += 1
                    continue

                # Determine cursor position for this frame.
                cursor_x, cursor_y, timestamp = self._cursor_at_frame(
                    frame_idx, cursor_by_frame
                )

                # Draw overlays.
                image = self._draw_overlay(
                    image, cursor_x, cursor_y, frame_idx, timestamp
                )
                frame_events = events_by_frame.get(frame_idx, [])
                if not frame_events:
                    frame_events = self._events_near_timestamp(timestamp)
                image = self._draw_events(image, frame_events)

                cv2.imshow(_WINDOW_NAME, image)

                # Compute wait time adjusted for playback speed.
                adjusted_delay = max(1, int(base_delay_ms / max(speed, 0.01)))

                key = cv2.waitKey(adjusted_delay) & 0xFF

                if key == ord("q"):
                    break
                elif key == ord(" "):
                    self._paused = not self._paused
                elif key == 83 or key == ord("d"):
                    # Right arrow (Windows cv2 code 83) or 'd'.
                    if self._paused:
                        frame_idx = min(
                            frame_idx + 1, self._session.frame_count - 1
                        )
                        continue
                elif key == 81 or key == ord("a"):
                    # Left arrow (Windows cv2 code 81) or 'a'.
                    if self._paused:
                        frame_idx = max(frame_idx - 1, 0)
                        continue

                if self._paused:
                    # While paused, keep showing the current frame.
                    while self._paused:
                        key = cv2.waitKey(50) & 0xFF
                        if key == ord("q"):
                            self._paused = False
                            cv2.destroyAllWindows()
                            return
                        elif key == ord(" "):
                            self._paused = False
                        elif key == 83 or key == ord("d"):
                            frame_idx = min(
                                frame_idx + 1,
                                self._session.frame_count - 1,
                            )
                            break
                        elif key == 81 or key == ord("a"):
                            frame_idx = max(frame_idx - 1, 0)
                            break
                    continue

                frame_idx += 1
        finally:
            cv2.destroyAllWindows()

    def _draw_overlay(
        self,
        frame: NDArray[np.uint8],
        cursor_x: int,
        cursor_y: int,
        frame_idx: int,
        timestamp: float,
    ) -> NDArray[np.uint8]:
        """Draw cursor circle, frame counter, and timestamp on the frame.

        Args:
            frame: The BGR image to annotate (modified in place).
            cursor_x: Cursor X coordinate.
            cursor_y: Cursor Y coordinate.
            frame_idx: Zero-based frame index.
            timestamp: Unix timestamp of the frame.

        Returns:
            The annotated image (same array, modified in place).
        """
        output = frame.copy()
        h, w = output.shape[:2]

        # Draw cursor as a filled circle with an outline ring.
        if 0 <= cursor_x < w and 0 <= cursor_y < h:
            cv2.circle(output, (cursor_x, cursor_y), 8, _CURSOR_OUTLINE, 2)
            cv2.circle(output, (cursor_x, cursor_y), 4, _CURSOR_COLOUR, -1)

        # Build info text.
        frame_text = f"Frame: {frame_idx + 1}/{self._session.frame_count}"
        time_text = f"Time: {timestamp:.3f}"
        speed_text = f"Cursor: ({cursor_x}, {cursor_y})"

        # Draw text with dark background for readability.
        y_offset = 20
        for text in [frame_text, time_text, speed_text]:
            text_size = cv2.getTextSize(
                text, _FONT, _FONT_SCALE, _FONT_THICKNESS
            )[0]
            cv2.rectangle(
                output,
                (8, y_offset - text_size[1] - 4),
                (8 + text_size[0] + 4, y_offset + 4),
                _TEXT_BG_COLOUR,
                -1,
            )
            cv2.putText(
                output,
                text,
                (10, y_offset),
                _FONT,
                _FONT_SCALE,
                _TEXT_COLOUR,
                _FONT_THICKNESS,
                cv2.LINE_AA,
            )
            y_offset += text_size[1] + 12

        # Draw pause indicator when paused.
        if self._paused:
            pause_text = "PAUSED (Space=resume, Arrows=step, Q=quit)"
            pt_size = cv2.getTextSize(
                pause_text, _FONT, _FONT_SCALE, _FONT_THICKNESS
            )[0]
            px = (w - pt_size[0]) // 2
            py = h - 20
            cv2.rectangle(
                output,
                (px - 4, py - pt_size[1] - 4),
                (px + pt_size[0] + 4, py + 4),
                _TEXT_BG_COLOUR,
                -1,
            )
            cv2.putText(
                output,
                pause_text,
                (px, py),
                _FONT,
                _FONT_SCALE,
                (0, 200, 255),
                _FONT_THICKNESS,
                cv2.LINE_AA,
            )

        return output

    def _draw_events(
        self,
        frame: NDArray[np.uint8],
        events_at_frame: list[dict[str, Any]],
    ) -> NDArray[np.uint8]:
        """Draw event annotations on the frame.

        Each event is rendered as a coloured marker at its position with
        a short label.  The colour depends on the event type.

        Args:
            frame: The BGR image to annotate (modified in place).
            events_at_frame: List of event dicts that apply to this
                frame.

        Returns:
            The annotated image.
        """
        if not events_at_frame:
            return frame

        h, w = frame.shape[:2]

        for event in events_at_frame:
            event_type = event.get("type", "")
            position = event.get("position")
            zone_id = event.get("zone_id", "")

            # Pick colour based on event type.
            colour = self._event_colour(event_type)

            # Draw marker at event position if available.
            if position and isinstance(position, (list, tuple)) and len(position) >= 2:
                ex, ey = int(position[0]), int(position[1])
                if 0 <= ex < w and 0 <= ey < h:
                    # Draw a diamond marker.
                    size = 6
                    pts = np.array(
                        [
                            [ex, ey - size],
                            [ex + size, ey],
                            [ex, ey + size],
                            [ex - size, ey],
                        ],
                        dtype=np.int32,
                    )
                    cv2.polylines(frame, [pts], True, colour, 2)

                    # Label with event type and zone id.
                    label = event_type
                    if zone_id:
                        label = f"{event_type} [{zone_id}]"
                    label_size = cv2.getTextSize(
                        label, _FONT, 0.4, 1
                    )[0]
                    lx = min(ex + 10, w - label_size[0] - 4)
                    ly = max(ey - 4, label_size[1] + 4)
                    cv2.rectangle(
                        frame,
                        (lx - 2, ly - label_size[1] - 2),
                        (lx + label_size[0] + 2, ly + 2),
                        _TEXT_BG_COLOUR,
                        -1,
                    )
                    cv2.putText(
                        frame,
                        label,
                        (lx, ly),
                        _FONT,
                        0.4,
                        colour,
                        1,
                        cv2.LINE_AA,
                    )

        return frame

    # -- Internal helpers ----------------------------------------------------

    def _build_cursor_index(self) -> dict[int, dict[str, Any]]:
        """Build a mapping from frame number to cursor sample.

        Returns:
            Dict keyed by ``frame`` number with cursor sample dicts
            as values.
        """
        index: dict[int, dict[str, Any]] = {}
        for sample in self._session.cursor_samples:
            frame_num = sample.get("frame")
            if frame_num is not None:
                index[int(frame_num)] = sample
        return index

    def _build_events_index(self) -> dict[int, list[dict[str, Any]]]:
        """Build a mapping from frame number to events at that frame.

        Events do not carry a ``frame`` field directly, so this method
        tries to correlate events to frames via timestamps.  If cursor
        samples exist, each event is assigned to the frame whose cursor
        sample has the closest timestamp.

        Returns:
            Dict keyed by zero-based frame index with lists of event
            dicts.
        """
        if not self._session.events:
            return {}
        if not self._session.cursor_samples:
            return {}

        # Build sorted list of (timestamp, frame_index) from cursor samples.
        ts_to_frame: list[tuple[float, int]] = []
        for sample in self._session.cursor_samples:
            ts = sample.get("timestamp", 0.0)
            frame_num = sample.get("frame", 0)
            # Cursor samples use 1-based frame numbers; convert to 0-based.
            ts_to_frame.append((float(ts), int(frame_num) - 1))
        ts_to_frame.sort()

        if not ts_to_frame:
            return {}

        index: dict[int, list[dict[str, Any]]] = {}
        for event in self._session.events:
            event_ts = float(event.get("timestamp", 0.0))
            # Binary search for closest cursor timestamp.
            best_frame = self._closest_frame(ts_to_frame, event_ts)
            if best_frame not in index:
                index[best_frame] = []
            index[best_frame].append(event)

        return index

    def _closest_frame(
        self,
        ts_to_frame: list[tuple[float, int]],
        target_ts: float,
    ) -> int:
        """Find the frame index closest to a given timestamp.

        Args:
            ts_to_frame: Sorted list of ``(timestamp, frame_index)``
                pairs.
            target_ts: The timestamp to match.

        Returns:
            Zero-based frame index of the closest cursor sample.
        """
        lo, hi = 0, len(ts_to_frame) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if ts_to_frame[mid][0] < target_ts:
                lo = mid + 1
            else:
                hi = mid

        # Compare neighbours to find the true closest.
        best_idx = lo
        if lo > 0:
            diff_lo = abs(ts_to_frame[lo - 1][0] - target_ts)
            diff_hi = abs(ts_to_frame[lo][0] - target_ts)
            if diff_lo < diff_hi:
                best_idx = lo - 1

        return ts_to_frame[best_idx][1]

    def _cursor_at_frame(
        self,
        frame_idx: int,
        cursor_by_frame: dict[int, dict[str, Any]],
    ) -> tuple[int, int, float]:
        """Look up cursor position for a given frame index.

        Frame PNGs use 1-based numbering (``000001.png``), so we look
        up ``frame_idx + 1`` in the cursor index.

        Args:
            frame_idx: Zero-based frame index.
            cursor_by_frame: Index built by ``_build_cursor_index``.

        Returns:
            Tuple of ``(cursor_x, cursor_y, timestamp)``.  Returns
            ``(0, 0, 0.0)`` if no cursor data is available for the
            frame.
        """
        # Cursor samples record 1-based frame numbers.
        sample = cursor_by_frame.get(frame_idx + 1)
        if sample is not None:
            return (
                int(sample.get("x", 0)),
                int(sample.get("y", 0)),
                float(sample.get("timestamp", 0.0)),
            )
        return (0, 0, 0.0)

    def _events_near_timestamp(
        self,
        timestamp: float,
        tolerance: float = 0.1,
    ) -> list[dict[str, Any]]:
        """Find events within a tolerance window of a timestamp.

        Used as a fallback when the events index has no entry for the
        current frame.

        Args:
            timestamp: The reference timestamp.
            tolerance: Maximum time difference in seconds.

        Returns:
            List of events whose timestamps fall within the window.
        """
        if timestamp <= 0.0:
            return []
        results: list[dict[str, Any]] = []
        for event in self._session.events:
            event_ts = float(event.get("timestamp", 0.0))
            if abs(event_ts - timestamp) <= tolerance:
                results.append(event)
        return results

    def _compute_frame_delay_ms(self) -> int:
        """Estimate per-frame delay from cursor sample timestamps.

        If the session has at least two cursor samples, uses the
        average interval between consecutive samples.  Otherwise falls
        back to the ``target_fps`` from metadata, or a default of
        67 ms (~15 fps).

        Returns:
            Delay in milliseconds between frames.
        """
        samples = self._session.cursor_samples
        if len(samples) >= 2:
            timestamps = [float(s.get("timestamp", 0.0)) for s in samples]
            timestamps.sort()
            total_span = timestamps[-1] - timestamps[0]
            if total_span > 0 and len(timestamps) > 1:
                avg_interval = total_span / (len(timestamps) - 1)
                return max(1, int(avg_interval * 1000))

        # Fallback: check metadata for target_fps.
        meta = self._session.metadata
        target_fps = meta.get("target_fps", 0)
        if isinstance(target_fps, (int, float)) and target_fps > 0:
            return max(1, int(1000 / target_fps))

        return 67  # ~15 fps default

    @staticmethod
    def _event_colour(event_type: str) -> tuple[int, int, int]:
        """Return a BGR colour for a given event type string.

        Args:
            event_type: The event type name (e.g. ``"ZONE_ENTER"``).

        Returns:
            A BGR colour tuple.
        """
        upper = event_type.upper()
        if "ENTER" in upper:
            return _EVENT_ENTER_COLOUR
        if "EXIT" in upper:
            return _EVENT_EXIT_COLOUR
        if "CLICK" in upper:
            return _EVENT_CLICK_COLOUR
        if "LOST" in upper:
            return _EVENT_LOST_COLOUR
        return _EVENT_DEFAULT_COLOUR


# ---------------------------------------------------------------------------
# Text summary
# ---------------------------------------------------------------------------


def print_summary(session: Session) -> None:
    """Print a text summary of a recorded session.

    Outputs session duration, frame count, event and action counts,
    the task description, and a timeline of key events (zone enters,
    clicks, brush lost).

    Args:
        session: A loaded ``Session`` instance.
    """
    meta = session.metadata
    session_id = meta.get("session_id", "unknown")
    start_time = float(meta.get("start_time", 0.0))
    end_time = float(meta.get("end_time", 0.0))
    duration = end_time - start_time if end_time > start_time else 0.0
    task_desc = meta.get("task_description", "(none)")
    screen_w = meta.get("screen_width", 0)
    screen_h = meta.get("screen_height", 0)
    frame_count_meta = meta.get("frame_count", 0)
    event_count_meta = meta.get("event_count", 0)
    action_count_meta = meta.get("action_count", 0)

    print("=" * 60)
    print(f"  Session: {session_id}")
    print("=" * 60)
    print(f"  Task:        {task_desc}")
    print(f"  Duration:    {duration:.2f}s")
    print(f"  Screen:      {screen_w}x{screen_h}")
    print(f"  Frames:      {frame_count_meta} (metadata)")
    print(f"               {session.frame_count} (on disk)")
    print(f"  Events:      {event_count_meta}")
    print(f"  Actions:     {action_count_meta}")
    print(f"  Cursor pts:  {len(session.cursor_samples)}")
    print("-" * 60)

    # Timeline of key events.
    key_types = {"ZONE_ENTER", "ZONE_CLICK", "ZONE_EXIT", "BRUSH_LOST"}
    key_events = [
        e
        for e in session.events
        if str(e.get("type", "")).upper() in key_types
    ]

    if key_events:
        # Sort by timestamp.
        key_events.sort(key=lambda e: float(e.get("timestamp", 0.0)))
        print("  Timeline of key events:")
        print("-" * 60)
        for event in key_events:
            event_type = event.get("type", "?")
            zone_id = event.get("zone_id", "")
            event_ts = float(event.get("timestamp", 0.0))
            position = event.get("position", [0, 0])
            relative_time = event_ts - start_time if start_time > 0 else 0.0

            pos_str = ""
            if isinstance(position, (list, tuple)) and len(position) >= 2:
                pos_str = f"({position[0]}, {position[1]})"

            zone_str = f" [{zone_id}]" if zone_id else ""
            print(
                f"  +{relative_time:8.3f}s  "
                f"{event_type}{zone_str}  {pos_str}"
            )
    else:
        print("  No key events recorded.")

    # Action summary.
    if session.actions:
        print("-" * 60)
        print("  Actions:")
        print("-" * 60)
        for i, action in enumerate(session.actions, start=1):
            action_type = action.get("type", "?")
            target = action.get("target_zone_id", "")
            status = action.get("status", "?")
            result = action.get("result", "")
            action_ts = float(action.get("timestamp", 0.0))
            relative_time = action_ts - start_time if start_time > 0 else 0.0

            target_str = f" -> {target}" if target else ""
            result_str = f" ({result})" if result else ""
            print(
                f"  {i:3d}. +{relative_time:8.3f}s  "
                f"{action_type}{target_str}  [{status}]{result_str}"
            )

    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the replay viewer CLI.

    Returns:
        Configured ``ArgumentParser``.
    """
    parser = argparse.ArgumentParser(
        prog="replay_viewer",
        description=(
            "CIU Agent replay viewer -- play back recorded sessions "
            "for debugging and analysis."
        ),
    )
    parser.add_argument(
        "--session",
        "-s",
        type=str,
        required=True,
        help="Path to the session directory to replay.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed multiplier (default: 1.0).",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        default=False,
        help="Print a text summary and exit without playing video.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help=(
            "Skip cv2 display (for CI environments). "
            "Prints the summary instead."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Entry point for the replay viewer CLI.

    Parses command-line arguments, loads the session, and either
    prints a summary or plays the session back in an OpenCV window.

    Args:
        argv: Command-line arguments.  Defaults to ``sys.argv[1:]``
            when ``None``.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    session_path = Path(args.session)
    loader = SessionLoader()

    try:
        session = loader.load(session_path)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print_summary(session)

    if args.summary_only or args.headless:
        return

    if session.frame_count == 0:
        print(
            "No frame PNGs found in session. "
            "Nothing to play back (was save_frames_as_png enabled?)."
        )
        return

    viewer = ReplayViewer(session)
    viewer.play(speed=args.speed)


if __name__ == "__main__":
    main()
