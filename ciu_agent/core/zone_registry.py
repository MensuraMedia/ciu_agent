"""Zone registry: CRUD storage and spatial queries for detected UI zones.

The ZoneRegistry is the single source of truth for all zones currently
known to the Canvas Mapper.  It provides fast lookup by ID, filtered
queries by label / type / state / spatial position, and lifecycle
helpers such as staleness expiration.

Thread-safe for concurrent reads but **not** for concurrent writes.
Callers that mutate the registry from multiple threads must synchronise
externally.

This module depends only on ``ciu_agent.models.zone`` and the Python
standard library.  It does not import any other ``core/`` modules.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any

from ciu_agent.models.zone import Zone, ZoneState, ZoneType


class ZoneRegistry:
    """Persistent registry of all detected interactive zones on screen.

    Provides CRUD operations, spatial queries, and zone lifecycle
    management.  Thread-safe for concurrent reads (but not concurrent
    writes).

    Example::

        registry = ZoneRegistry()
        registry.register(zone)
        hits = registry.find_at_point(400, 300)
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        """Initialize an empty zone registry."""
        self._zones: dict[str, Zone] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, zone: Zone) -> None:
        """Add a zone to the registry.  Overwrites if ID already exists.

        Args:
            zone: The zone to register.
        """
        with self._lock:
            self._zones[zone.id] = zone

    def register_many(self, zones: list[Zone]) -> None:
        """Register multiple zones at once.

        Args:
            zones: A list of zones to add.  Existing IDs are
                overwritten.
        """
        with self._lock:
            for zone in zones:
                self._zones[zone.id] = zone

    def update(self, zone_id: str, **kwargs: Any) -> Zone:
        """Update fields of an existing zone.

        Creates a new ``Zone`` instance with the requested field values
        changed (via ``dataclasses.replace``) and stores it under the
        same ID.

        Args:
            zone_id: The zone to update.
            **kwargs: Fields to update (e.g.
                ``state=ZoneState.FOCUSED, label="New"``).

        Returns:
            The newly created ``Zone`` with updated fields.

        Raises:
            KeyError: If *zone_id* is not in the registry.
        """
        with self._lock:
            if zone_id not in self._zones:
                raise KeyError(
                    f"Zone '{zone_id}' not found in registry"
                )
            updated = replace(self._zones[zone_id], **kwargs)
            self._zones[zone_id] = updated
            return updated

    def remove(self, zone_id: str) -> Zone:
        """Remove a zone from the registry.

        Args:
            zone_id: The ID of the zone to remove.

        Returns:
            The removed ``Zone`` instance.

        Raises:
            KeyError: If *zone_id* is not in the registry.
        """
        with self._lock:
            if zone_id not in self._zones:
                raise KeyError(
                    f"Zone '{zone_id}' not found in registry"
                )
            return self._zones.pop(zone_id)

    def get(self, zone_id: str) -> Zone | None:
        """Get a zone by ID.

        Args:
            zone_id: The ID to look up.

        Returns:
            The matching ``Zone``, or ``None`` if not found.
        """
        return self._zones.get(zone_id)

    def contains(self, zone_id: str) -> bool:
        """Check if a zone ID exists in the registry.

        Args:
            zone_id: The ID to test.

        Returns:
            ``True`` if the ID is present.
        """
        return zone_id in self._zones

    def clear(self) -> None:
        """Remove all zones from the registry."""
        with self._lock:
            self._zones.clear()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def find_by_label(self, label: str) -> list[Zone]:
        """Find zones whose label contains the given text.

        The search is case-insensitive.

        Args:
            label: Substring to match against zone labels.

        Returns:
            A list of matching zones (may be empty).
        """
        needle = label.lower()
        return [
            z for z in self._zones.values()
            if needle in z.label.lower()
        ]

    def find_by_type(self, zone_type: ZoneType) -> list[Zone]:
        """Find all zones of a given type.

        Args:
            zone_type: The ``ZoneType`` to filter on.

        Returns:
            A list of matching zones (may be empty).
        """
        return [
            z for z in self._zones.values()
            if z.type is zone_type
        ]

    def find_by_state(self, state: ZoneState) -> list[Zone]:
        """Find all zones in a given state.

        Args:
            state: The ``ZoneState`` to filter on.

        Returns:
            A list of matching zones (may be empty).
        """
        return [
            z for z in self._zones.values()
            if z.state is state
        ]

    def find_at_point(self, x: int, y: int) -> list[Zone]:
        """Find all zones containing the given screen point.

        Returns zones ordered by area (smallest first), since smaller
        zones are more likely the intended interaction target.

        Args:
            x: X-coordinate in screen pixels.
            y: Y-coordinate in screen pixels.

        Returns:
            A list of zones that contain the point, sorted by
            ascending area.
        """
        hits = [
            z for z in self._zones.values()
            if z.contains_point(x, y)
        ]
        hits.sort(key=lambda z: z.bounds.area())
        return hits

    def find_by_parent(self, parent_id: str) -> list[Zone]:
        """Find all direct children of a parent zone.

        Args:
            parent_id: The ``id`` of the parent zone.

        Returns:
            A list of zones whose ``parent_id`` matches.
        """
        return [
            z for z in self._zones.values()
            if z.parent_id == parent_id
        ]

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def get_all(self) -> list[Zone]:
        """Return all zones currently in the registry.

        Returns:
            A list of every registered ``Zone``.  The order is not
            guaranteed.
        """
        return list(self._zones.values())

    def replace_all(self, zones: list[Zone]) -> None:
        """Replace the entire registry contents with *zones*.

        This is the expected entry-point after a Tier 2 full-screen
        rebuild, where the previous zone set is discarded entirely.

        Args:
            zones: The new complete set of zones.
        """
        with self._lock:
            self._zones.clear()
            for zone in zones:
                self._zones[zone.id] = zone

    def expire_stale(
        self,
        current_time: float,
        max_age_seconds: float,
    ) -> list[Zone]:
        """Remove zones whose ``last_seen`` is older than *max_age_seconds*.

        Args:
            current_time: The reference timestamp (Unix seconds).
            max_age_seconds: Maximum allowed age in seconds.  Zones
                with ``current_time - zone.last_seen > max_age_seconds``
                are removed.

        Returns:
            A list of the removed (stale) zones.
        """
        cutoff = current_time - max_age_seconds
        with self._lock:
            stale: list[Zone] = [
                z for z in self._zones.values()
                if z.last_seen < cutoff
            ]
            for z in stale:
                del self._zones[z.id]
        return stale

    def update_last_seen(
        self,
        zone_id: str,
        timestamp: float,
    ) -> None:
        """Update the ``last_seen`` timestamp of a zone.

        Args:
            zone_id: The zone whose timestamp should be refreshed.
            timestamp: The new ``last_seen`` value (Unix seconds).

        Raises:
            KeyError: If *zone_id* is not in the registry.
        """
        with self._lock:
            if zone_id not in self._zones:
                raise KeyError(
                    f"Zone '{zone_id}' not found in registry"
                )
            self._zones[zone_id] = replace(
                self._zones[zone_id],
                last_seen=timestamp,
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Number of zones in the registry."""
        return len(self._zones)

    @property
    def zone_ids(self) -> list[str]:
        """List of all zone IDs in the registry."""
        return list(self._zones.keys())

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return the number of zones (mirrors ``count``)."""
        return len(self._zones)

    def __contains__(self, zone_id: object) -> bool:
        """Support ``zone_id in registry`` syntax."""
        if not isinstance(zone_id, str):
            return False
        return zone_id in self._zones

    def __repr__(self) -> str:
        """Human-readable summary of the registry."""
        return f"ZoneRegistry(count={self.count})"
