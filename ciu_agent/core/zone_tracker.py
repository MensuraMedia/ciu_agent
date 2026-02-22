"""Zone tracker: continuous cursor-to-zone tracking with spatial event emission.

The ZoneTracker is a sub-component of the Brush Controller (Phase 3).
Each frame, it receives the current cursor position, resolves the zone
under the cursor via the ZoneRegistry, and emits spatial events when
the cursor enters, exits, or hovers over a zone.

This module depends only on ``ciu_agent.models``, ``ciu_agent.core.zone_registry``,
and ``ciu_agent.config.settings``.  It does not import any other ``core/`` modules.
"""

from __future__ import annotations

from collections import deque

from ciu_agent.config.settings import Settings
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.events import SpatialEvent, SpatialEventType
from ciu_agent.models.zone import Zone

_DEFAULT_HISTORY_MAXLEN: int = 1000


class ZoneTracker:
    """Tracks cursor position against the zone registry and emits spatial events.

    Called once per frame with the current cursor coordinates, the tracker
    resolves which zone (if any) the cursor occupies, detects transitions
    (enter / exit), and fires a single hover event once the cursor has
    dwelled in a zone for longer than the configured threshold.

    Example::

        tracker = ZoneTracker(registry, settings)
        events = tracker.update((400, 300), time.monotonic())
        for ev in events:
            print(ev.type, ev.zone_id)

    Attributes:
        registry: The zone registry used for spatial lookups.
        settings: Configuration snapshot providing ``hover_threshold_ms``.
    """

    def __init__(
        self,
        registry: ZoneRegistry,
        settings: Settings,
        *,
        history_maxlen: int = _DEFAULT_HISTORY_MAXLEN,
    ) -> None:
        """Initialise the zone tracker.

        Args:
            registry: Zone registry providing ``find_at_point``.
            settings: Agent settings (uses ``hover_threshold_ms``).
            history_maxlen: Maximum number of events retained in the
                internal history deque.  Defaults to 1000.
        """
        self._registry: ZoneRegistry = registry
        self._settings: Settings = settings

        # Tracking state
        self._current_zone_id: str | None = None
        self._zone_enter_time: float | None = None
        self._hover_start_time: float | None = None
        self._is_hovering: bool = False
        self._hover_emitted: bool = False
        self._last_position: tuple[int, int] | None = None

        # Event history
        self._history: deque[SpatialEvent] = deque(maxlen=history_maxlen)

    # ------------------------------------------------------------------
    # Public read-only properties
    # ------------------------------------------------------------------

    @property
    def registry(self) -> ZoneRegistry:
        """The zone registry used for spatial lookups."""
        return self._registry

    @property
    def settings(self) -> Settings:
        """Configuration snapshot providing hover_threshold_ms."""
        return self._settings

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update(
        self,
        cursor_pos: tuple[int, int],
        timestamp: float,
    ) -> list[SpatialEvent]:
        """Process one frame of cursor tracking.

        Resolves the zone under the cursor, emits enter/exit events on
        transitions, and emits a single hover event once the dwell
        threshold is exceeded.

        Args:
            cursor_pos: Current cursor screen coordinates ``(x, y)``.
            timestamp: Unix timestamp (or monotonic clock) for this frame.

        Returns:
            A list of ``SpatialEvent`` instances emitted during this
            frame.  May be empty if nothing changed.
        """
        x, y = cursor_pos
        events: list[SpatialEvent] = []

        # Find zones under cursor (smallest-first).
        hits = self._registry.find_at_point(x, y)
        new_zone_id: str | None = hits[0].id if hits else None

        # ----- Zone transition detection -----

        if new_zone_id != self._current_zone_id:
            # Exiting old zone
            if self._current_zone_id is not None:
                duration = self._compute_zone_duration(timestamp)
                exit_event = SpatialEvent(
                    type=SpatialEventType.ZONE_EXIT,
                    zone_id=self._current_zone_id,
                    timestamp=timestamp,
                    position=cursor_pos,
                    data={"duration": duration},
                )
                events.append(exit_event)

            # Entering new zone
            if new_zone_id is not None:
                enter_event = SpatialEvent(
                    type=SpatialEventType.ZONE_ENTER,
                    zone_id=new_zone_id,
                    timestamp=timestamp,
                    position=cursor_pos,
                    data={},
                )
                events.append(enter_event)

            # Reset tracking state for the new zone
            self._current_zone_id = new_zone_id
            self._zone_enter_time = timestamp if new_zone_id is not None else None
            self._hover_start_time = timestamp if new_zone_id is not None else None
            self._is_hovering = new_zone_id is not None
            self._hover_emitted = False

        else:
            # Cursor stayed in the same zone (or still outside all zones).
            if self._current_zone_id is not None and not self._hover_emitted:
                self._check_hover(cursor_pos, timestamp, events)

        self._last_position = cursor_pos

        # Record emitted events in history.
        for ev in events:
            self._history.append(ev)

        return events

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_current_zone(self) -> str | None:
        """Return the ID of the zone the cursor currently occupies.

        Returns:
            The zone ID string, or ``None`` if the cursor is not inside
            any registered zone.
        """
        return self._current_zone_id

    def get_current_zone_object(self) -> Zone | None:
        """Return the full Zone object the cursor currently occupies.

        Returns:
            The ``Zone`` instance from the registry, or ``None`` if the
            cursor is not inside any registered zone or the zone has
            been removed from the registry since the last update.
        """
        if self._current_zone_id is None:
            return None
        return self._registry.get(self._current_zone_id)

    def get_event_history(self, limit: int = 50) -> list[SpatialEvent]:
        """Return the most recent spatial events from the internal history.

        Events are returned in chronological order (oldest first).

        Args:
            limit: Maximum number of events to return.  Clamped to the
                size of the history if fewer events are available.

        Returns:
            A list of up to *limit* most recent ``SpatialEvent`` objects.
        """
        if limit <= 0:
            return []
        # Slice the last `limit` items from the deque.
        if limit >= len(self._history):
            return list(self._history)
        return list(self._history)[-limit:]

    def is_in_zone(self, zone_id: str) -> bool:
        """Check if the cursor is currently inside a specific zone.

        Args:
            zone_id: The zone ID to test against.

        Returns:
            ``True`` if the cursor is currently inside the zone with
            the given ID.
        """
        return self._current_zone_id == zone_id

    def get_hover_duration(self, timestamp: float) -> float | None:
        """Return the current hover duration in seconds, if hovering.

        The hover duration is measured from the moment the cursor
        entered the current zone, regardless of whether the hover
        threshold has been reached.

        Args:
            timestamp: The reference timestamp to compute the elapsed
                time against.

        Returns:
            Duration in seconds the cursor has been dwelling in the
            current zone, or ``None`` if the cursor is not in any zone.
        """
        if (
            self._current_zone_id is None
            or self._hover_start_time is None
        ):
            return None
        return timestamp - self._hover_start_time

    def reset(self) -> None:
        """Clear all tracking state and event history.

        After calling this method the tracker behaves as if freshly
        constructed — no current zone, no pending hover, and an empty
        event history.
        """
        self._current_zone_id = None
        self._zone_enter_time = None
        self._hover_start_time = None
        self._is_hovering = False
        self._hover_emitted = False
        self._last_position = None
        self._history.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_zone_duration(self, timestamp: float) -> float:
        """Compute how long the cursor has been in the current zone.

        Args:
            timestamp: The current frame timestamp.

        Returns:
            Duration in seconds since the cursor entered the zone.
            Returns ``0.0`` if entry time was not recorded.
        """
        if self._zone_enter_time is None:
            return 0.0
        return timestamp - self._zone_enter_time

    def _check_hover(
        self,
        cursor_pos: tuple[int, int],
        timestamp: float,
        events: list[SpatialEvent],
    ) -> None:
        """Check if the hover threshold has been exceeded and emit an event.

        This method is called only when the cursor has remained inside
        the same zone between frames and no hover event has been emitted
        yet for this visit.

        Args:
            cursor_pos: Current cursor screen coordinates.
            timestamp: Current frame timestamp.
            events: Mutable list to which a hover event is appended if
                the threshold is met.
        """
        if self._hover_start_time is None:
            return

        elapsed_ms = (timestamp - self._hover_start_time) * 1000.0
        if elapsed_ms >= self._settings.hover_threshold_ms:
            hover_event = SpatialEvent(
                type=SpatialEventType.ZONE_HOVER,
                zone_id=self._current_zone_id or "",
                timestamp=timestamp,
                position=cursor_pos,
                data={
                    "duration": (timestamp - self._hover_start_time),
                },
            )
            events.append(hover_event)
            self._hover_emitted = True

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """Human-readable summary of the tracker state."""
        zone = self._current_zone_id or "none"
        return (
            f"ZoneTracker(current_zone={zone!r}, "
            f"hovering={self._is_hovering}, "
            f"history={len(self._history)})"
        )
