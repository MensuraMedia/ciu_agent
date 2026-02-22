"""Comprehensive unit tests for ciu_agent.core.zone_registry.ZoneRegistry.

Covers CRUD operations, query methods, bulk operations, properties,
dunder methods, edge cases, and thread safety.
"""

from __future__ import annotations

import threading

import pytest

from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.zone import Rectangle, Zone, ZoneState, ZoneType

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_zone(
    zone_id: str = "z1",
    x: int = 0,
    y: int = 0,
    width: int = 100,
    height: int = 50,
    zone_type: ZoneType = ZoneType.BUTTON,
    label: str = "OK",
    state: ZoneState = ZoneState.ENABLED,
    confidence: float = 0.9,
    last_seen: float = 1000.0,
    parent_id: str | None = None,
) -> Zone:
    """Shorthand factory for building Zone instances in tests."""
    return Zone(
        id=zone_id,
        bounds=Rectangle(x=x, y=y, width=width, height=height),
        type=zone_type,
        label=label,
        state=state,
        confidence=confidence,
        last_seen=last_seen,
        parent_id=parent_id,
    )


@pytest.fixture()
def registry() -> ZoneRegistry:
    """Return a fresh empty ZoneRegistry for each test."""
    return ZoneRegistry()


@pytest.fixture()
def populated_registry() -> ZoneRegistry:
    """Return a ZoneRegistry pre-loaded with a handful of varied zones."""
    reg = ZoneRegistry()
    reg.register_many(
        [
            _make_zone(
                "btn_save", 10, 10, 80, 30, ZoneType.BUTTON, "Save", ZoneState.ENABLED, 0.95, 1000.0
            ),
            _make_zone(
                "btn_cancel",
                100,
                10,
                80,
                30,
                ZoneType.BUTTON,
                "Cancel",
                ZoneState.DISABLED,
                0.90,
                999.0,
            ),
            _make_zone(
                "txt_name",
                10,
                60,
                200,
                25,
                ZoneType.TEXT_FIELD,
                "Name",
                ZoneState.FOCUSED,
                0.85,
                1001.0,
            ),
            _make_zone(
                "link_help", 300, 400, 60, 20, ZoneType.LINK, "Help", ZoneState.ENABLED, 0.80, 998.0
            ),
            _make_zone(
                "chk_agree",
                10,
                100,
                20,
                20,
                ZoneType.CHECKBOX,
                "I agree",
                ZoneState.UNCHECKED,
                0.88,
                997.0,
            ),
        ]
    )
    return reg


# ==================================================================
# CRUD
# ==================================================================


class TestRegister:
    """Tests for ZoneRegistry.register."""

    def test_register_single_zone(self, registry: ZoneRegistry) -> None:
        zone = _make_zone("z1")
        registry.register(zone)
        assert registry.count == 1
        assert registry.get("z1") is zone

    def test_register_overwrites_existing_id(self, registry: ZoneRegistry) -> None:
        zone_v1 = _make_zone("z1", label="Version 1")
        zone_v2 = _make_zone("z1", label="Version 2")
        registry.register(zone_v1)
        registry.register(zone_v2)
        assert registry.count == 1
        assert registry.get("z1") is zone_v2
        assert registry.get("z1").label == "Version 2"

    def test_register_multiple_distinct_ids(self, registry: ZoneRegistry) -> None:
        for i in range(5):
            registry.register(_make_zone(f"z{i}"))
        assert registry.count == 5


class TestRegisterMany:
    """Tests for ZoneRegistry.register_many."""

    def test_register_many_adds_all(self, registry: ZoneRegistry) -> None:
        zones = [_make_zone(f"z{i}") for i in range(4)]
        registry.register_many(zones)
        assert registry.count == 4

    def test_register_many_empty_list(self, registry: ZoneRegistry) -> None:
        registry.register_many([])
        assert registry.count == 0

    def test_register_many_overwrites_duplicates(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", label="old"))
        registry.register_many([_make_zone("z1", label="new")])
        assert registry.get("z1").label == "new"
        assert registry.count == 1


class TestUpdate:
    """Tests for ZoneRegistry.update."""

    def test_update_changes_field(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", label="Old"))
        updated = registry.update("z1", label="New")
        assert updated.label == "New"
        assert registry.get("z1").label == "New"

    def test_update_returns_new_instance(self, registry: ZoneRegistry) -> None:
        original = _make_zone("z1")
        registry.register(original)
        updated = registry.update("z1", state=ZoneState.FOCUSED)
        assert updated is not original
        assert updated.state is ZoneState.FOCUSED
        assert original.state is ZoneState.ENABLED

    def test_update_preserves_unchanged_fields(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", label="Keep", confidence=0.75))
        updated = registry.update("z1", state=ZoneState.HOVERED)
        assert updated.label == "Keep"
        assert updated.confidence == 0.75

    def test_update_multiple_fields(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1"))
        updated = registry.update("z1", label="Changed", state=ZoneState.DISABLED)
        assert updated.label == "Changed"
        assert updated.state is ZoneState.DISABLED

    def test_update_nonexistent_raises_key_error(self, registry: ZoneRegistry) -> None:
        with pytest.raises(KeyError, match="not_here"):
            registry.update("not_here", label="X")


class TestRemove:
    """Tests for ZoneRegistry.remove."""

    def test_remove_existing_zone(self, registry: ZoneRegistry) -> None:
        zone = _make_zone("z1")
        registry.register(zone)
        removed = registry.remove("z1")
        assert removed is zone
        assert registry.count == 0

    def test_remove_nonexistent_raises_key_error(self, registry: ZoneRegistry) -> None:
        with pytest.raises(KeyError, match="ghost"):
            registry.remove("ghost")

    def test_remove_only_affects_target(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1"))
        registry.register(_make_zone("z2"))
        registry.remove("z1")
        assert registry.count == 1
        assert registry.get("z2") is not None
        assert registry.get("z1") is None


class TestGet:
    """Tests for ZoneRegistry.get."""

    def test_get_existing(self, registry: ZoneRegistry) -> None:
        zone = _make_zone("z1")
        registry.register(zone)
        assert registry.get("z1") is zone

    def test_get_nonexistent_returns_none(self, registry: ZoneRegistry) -> None:
        assert registry.get("missing") is None


class TestContains:
    """Tests for ZoneRegistry.contains."""

    def test_contains_true(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1"))
        assert registry.contains("z1") is True

    def test_contains_false(self, registry: ZoneRegistry) -> None:
        assert registry.contains("z1") is False


class TestClear:
    """Tests for ZoneRegistry.clear."""

    def test_clear_empties_registry(self, populated_registry: ZoneRegistry) -> None:
        assert populated_registry.count > 0
        populated_registry.clear()
        assert populated_registry.count == 0

    def test_clear_on_empty_registry(self, registry: ZoneRegistry) -> None:
        registry.clear()
        assert registry.count == 0


# ==================================================================
# Queries
# ==================================================================


class TestFindByLabel:
    """Tests for ZoneRegistry.find_by_label."""

    def test_exact_match(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_label("Save")
        assert len(results) == 1
        assert results[0].id == "btn_save"

    def test_case_insensitive(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_label("save")
        assert len(results) == 1
        assert results[0].id == "btn_save"

    def test_substring_match(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_label("anc")
        assert len(results) == 1
        assert results[0].id == "btn_cancel"

    def test_no_match(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_label("XYZ_NO_MATCH")
        assert results == []

    def test_empty_label_matches_all(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_label("")
        assert len(results) == populated_registry.count

    def test_multiple_matches(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", label="Submit Form"))
        registry.register(_make_zone("z2", label="submit data"))
        registry.register(_make_zone("z3", label="Cancel"))
        results = registry.find_by_label("submit")
        assert len(results) == 2


class TestFindByType:
    """Tests for ZoneRegistry.find_by_type."""

    def test_find_buttons(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_type(ZoneType.BUTTON)
        assert len(results) == 2
        ids = {z.id for z in results}
        assert ids == {"btn_save", "btn_cancel"}

    def test_find_type_no_match(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_type(ZoneType.SLIDER)
        assert results == []

    def test_find_single_type(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_type(ZoneType.CHECKBOX)
        assert len(results) == 1
        assert results[0].id == "chk_agree"


class TestFindByState:
    """Tests for ZoneRegistry.find_by_state."""

    def test_find_enabled(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_state(ZoneState.ENABLED)
        ids = {z.id for z in results}
        assert "btn_save" in ids
        assert "link_help" in ids

    def test_find_disabled(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_state(ZoneState.DISABLED)
        assert len(results) == 1
        assert results[0].id == "btn_cancel"

    def test_find_state_no_match(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_by_state(ZoneState.PRESSED)
        assert results == []


class TestFindAtPoint:
    """Tests for ZoneRegistry.find_at_point."""

    def test_point_inside_single_zone(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", 10, 10, 100, 50))
        results = registry.find_at_point(50, 30)
        assert len(results) == 1
        assert results[0].id == "z1"

    def test_point_outside_all_zones(self, populated_registry: ZoneRegistry) -> None:
        results = populated_registry.find_at_point(9999, 9999)
        assert results == []

    def test_sorted_by_area_ascending(self, registry: ZoneRegistry) -> None:
        big = _make_zone("big", 0, 0, 500, 500)
        medium = _make_zone("med", 10, 10, 100, 100)
        small = _make_zone("sml", 20, 20, 30, 30)
        registry.register_many([big, medium, small])
        results = registry.find_at_point(25, 25)
        assert len(results) == 3
        assert results[0].id == "sml"
        assert results[1].id == "med"
        assert results[2].id == "big"

    def test_point_on_boundary(self, registry: ZoneRegistry) -> None:
        zone = _make_zone("z1", 10, 10, 100, 50)
        registry.register(zone)
        # top-left corner
        assert len(registry.find_at_point(10, 10)) == 1
        # bottom-right corner (x+width, y+height)
        assert len(registry.find_at_point(110, 60)) == 1

    def test_point_just_outside_boundary(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", 10, 10, 100, 50))
        assert len(registry.find_at_point(9, 10)) == 0
        assert len(registry.find_at_point(111, 10)) == 0
        assert len(registry.find_at_point(10, 9)) == 0
        assert len(registry.find_at_point(10, 61)) == 0


class TestFindByParent:
    """Tests for ZoneRegistry.find_by_parent."""

    def test_find_children(self, registry: ZoneRegistry) -> None:
        parent = _make_zone("parent", 0, 0, 300, 300)
        child_a = _make_zone("child_a", 10, 10, 50, 20, parent_id="parent")
        child_b = _make_zone("child_b", 70, 10, 50, 20, parent_id="parent")
        orphan = _make_zone("orphan", 200, 200, 50, 20)
        registry.register_many([parent, child_a, child_b, orphan])
        children = registry.find_by_parent("parent")
        ids = {z.id for z in children}
        assert ids == {"child_a", "child_b"}

    def test_find_by_parent_no_children(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("lonely"))
        assert registry.find_by_parent("lonely") == []

    def test_find_by_parent_nonexistent_parent(self, registry: ZoneRegistry) -> None:
        assert registry.find_by_parent("no_such_parent") == []


# ==================================================================
# Bulk operations
# ==================================================================


class TestGetAll:
    """Tests for ZoneRegistry.get_all."""

    def test_get_all_returns_all_zones(self, populated_registry: ZoneRegistry) -> None:
        zones = populated_registry.get_all()
        assert len(zones) == populated_registry.count

    def test_get_all_empty(self, registry: ZoneRegistry) -> None:
        assert registry.get_all() == []

    def test_get_all_returns_list_copy(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1"))
        list_a = registry.get_all()
        list_b = registry.get_all()
        assert list_a is not list_b


class TestReplaceAll:
    """Tests for ZoneRegistry.replace_all."""

    def test_replace_all_clears_old_zones(self, populated_registry: ZoneRegistry) -> None:
        new_zone = _make_zone("brand_new")
        populated_registry.replace_all([new_zone])
        assert populated_registry.count == 1
        assert populated_registry.get("brand_new") is new_zone
        assert populated_registry.get("btn_save") is None

    def test_replace_all_with_empty_list(self, populated_registry: ZoneRegistry) -> None:
        populated_registry.replace_all([])
        assert populated_registry.count == 0

    def test_replace_all_idempotent(self, registry: ZoneRegistry) -> None:
        zones = [_make_zone("a"), _make_zone("b")]
        registry.replace_all(zones)
        registry.replace_all(zones)
        assert registry.count == 2


class TestExpireStale:
    """Tests for ZoneRegistry.expire_stale."""

    def test_expire_removes_old_zones(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("old", last_seen=100.0))
        registry.register(_make_zone("fresh", last_seen=208.0))
        stale = registry.expire_stale(current_time=210.0, max_age_seconds=5.0)
        assert len(stale) == 1
        assert stale[0].id == "old"
        assert registry.count == 1
        assert registry.get("fresh") is not None

    def test_expire_none_stale(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", last_seen=100.0))
        stale = registry.expire_stale(current_time=100.0, max_age_seconds=5.0)
        assert stale == []
        assert registry.count == 1

    def test_expire_all_stale(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", last_seen=10.0))
        registry.register(_make_zone("z2", last_seen=20.0))
        stale = registry.expire_stale(current_time=100.0, max_age_seconds=1.0)
        assert len(stale) == 2
        assert registry.count == 0

    def test_expire_boundary_exactly_at_cutoff(self, registry: ZoneRegistry) -> None:
        # Zone last_seen == cutoff => last_seen is NOT < cutoff => kept
        registry.register(_make_zone("z1", last_seen=95.0))
        stale = registry.expire_stale(current_time=100.0, max_age_seconds=5.0)
        assert stale == []
        assert registry.count == 1

    def test_expire_just_past_cutoff(self, registry: ZoneRegistry) -> None:
        # Zone last_seen just below cutoff => removed
        registry.register(_make_zone("z1", last_seen=94.9))
        stale = registry.expire_stale(current_time=100.0, max_age_seconds=5.0)
        assert len(stale) == 1

    def test_expire_on_empty_registry(self, registry: ZoneRegistry) -> None:
        stale = registry.expire_stale(current_time=100.0, max_age_seconds=1.0)
        assert stale == []

    def test_expire_zero_max_age(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", last_seen=100.0))
        stale = registry.expire_stale(current_time=100.0, max_age_seconds=0.0)
        # cutoff = 100.0 - 0.0 = 100.0; last_seen (100.0) is NOT < 100.0
        assert stale == []
        assert registry.count == 1


class TestUpdateLastSeen:
    """Tests for ZoneRegistry.update_last_seen."""

    def test_update_last_seen_changes_timestamp(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", last_seen=100.0))
        registry.update_last_seen("z1", 200.0)
        assert registry.get("z1").last_seen == 200.0

    def test_update_last_seen_nonexistent_raises_key_error(self, registry: ZoneRegistry) -> None:
        with pytest.raises(KeyError, match="nope"):
            registry.update_last_seen("nope", 123.0)

    def test_update_last_seen_creates_new_instance(self, registry: ZoneRegistry) -> None:
        original = _make_zone("z1", last_seen=100.0)
        registry.register(original)
        registry.update_last_seen("z1", 200.0)
        current = registry.get("z1")
        assert current is not original
        assert current.last_seen == 200.0
        assert original.last_seen == 100.0


# ==================================================================
# Properties
# ==================================================================


class TestProperties:
    """Tests for count, zone_ids, and related properties."""

    def test_count_empty(self, registry: ZoneRegistry) -> None:
        assert registry.count == 0

    def test_count_after_additions(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("a"))
        registry.register(_make_zone("b"))
        assert registry.count == 2

    def test_zone_ids_empty(self, registry: ZoneRegistry) -> None:
        assert registry.zone_ids == []

    def test_zone_ids_contents(self, populated_registry: ZoneRegistry) -> None:
        ids = set(populated_registry.zone_ids)
        assert ids == {"btn_save", "btn_cancel", "txt_name", "link_help", "chk_agree"}

    def test_zone_ids_returns_list_copy(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1"))
        ids_a = registry.zone_ids
        ids_b = registry.zone_ids
        assert ids_a is not ids_b


# ==================================================================
# Dunder methods
# ==================================================================


class TestDunderMethods:
    """Tests for __len__, __contains__, and __repr__."""

    def test_len_empty(self, registry: ZoneRegistry) -> None:
        assert len(registry) == 0

    def test_len_matches_count(self, populated_registry: ZoneRegistry) -> None:
        assert len(populated_registry) == populated_registry.count

    def test_contains_with_existing_id(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1"))
        assert "z1" in registry

    def test_contains_with_missing_id(self, registry: ZoneRegistry) -> None:
        assert "z1" not in registry

    def test_contains_with_non_string_returns_false(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1"))
        assert 42 not in registry  # type: ignore[operator]
        assert None not in registry  # type: ignore[operator]

    def test_repr_format(self, registry: ZoneRegistry) -> None:
        assert repr(registry) == "ZoneRegistry(count=0)"
        registry.register(_make_zone("z1"))
        assert repr(registry) == "ZoneRegistry(count=1)"


# ==================================================================
# Thread safety
# ==================================================================


class TestThreadSafety:
    """Verify that mutations acquire the internal lock.

    These tests are not exhaustive concurrency proofs but confirm that
    the lock is used and that concurrent operations do not corrupt state.
    """

    def test_lock_is_present(self, registry: ZoneRegistry) -> None:
        assert hasattr(registry, "_lock")
        assert isinstance(registry._lock, type(threading.Lock()))

    def test_concurrent_registers(self, registry: ZoneRegistry) -> None:
        """Many threads register distinct zones simultaneously."""
        n_threads = 20
        barrier = threading.Barrier(n_threads)

        def _register(i: int) -> None:
            barrier.wait()
            registry.register(_make_zone(f"z{i}"))

        threads = [threading.Thread(target=_register, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert registry.count == n_threads

    def test_concurrent_register_and_remove(self, registry: ZoneRegistry) -> None:
        """One thread registers, another removes; no exceptions raised."""
        zone = _make_zone("shared")
        registry.register(zone)

        def _register_loop() -> None:
            for _ in range(100):
                registry.register(_make_zone("shared"))

        def _remove_loop() -> None:
            for _ in range(100):
                try:
                    registry.remove("shared")
                except KeyError:
                    pass  # Expected when the other thread hasn't re-added yet

        t1 = threading.Thread(target=_register_loop)
        t2 = threading.Thread(target=_remove_loop)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Should finish without unexpected exceptions; final count is 0 or 1
        assert registry.count in (0, 1)

    def test_concurrent_expire_stale(self, registry: ZoneRegistry) -> None:
        """Multiple threads expire stale zones without corruption."""
        for i in range(50):
            registry.register(_make_zone(f"z{i}", last_seen=float(i)))

        barrier = threading.Barrier(4)

        def _expire() -> None:
            barrier.wait()
            registry.expire_stale(current_time=100.0, max_age_seconds=50.0)

        threads = [threading.Thread(target=_expire) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All zones with last_seen < 50.0 should be removed
        # Zones with last_seen 50..49 remain
        for z in registry.get_all():
            assert z.last_seen >= 50.0

    def test_concurrent_replace_all(self, registry: ZoneRegistry) -> None:
        """Concurrent replace_all calls do not corrupt internal dict."""
        set_a = [_make_zone(f"a{i}") for i in range(10)]
        set_b = [_make_zone(f"b{i}") for i in range(10)]
        barrier = threading.Barrier(2)

        def _replace(zones: list[Zone]) -> None:
            barrier.wait()
            registry.replace_all(zones)

        t1 = threading.Thread(target=_replace, args=(set_a,))
        t2 = threading.Thread(target=_replace, args=(set_b,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # One of the sets should have won; count must be exactly 10
        assert registry.count == 10


# ==================================================================
# Edge cases
# ==================================================================


class TestEdgeCases:
    """Miscellaneous edge-case and regression tests."""

    def test_register_and_get_preserves_identity(self, registry: ZoneRegistry) -> None:
        zone = _make_zone("z1")
        registry.register(zone)
        assert registry.get("z1") is zone

    def test_update_id_field(self, registry: ZoneRegistry) -> None:
        """Updating the id via kwargs is legal but the old key persists."""
        registry.register(_make_zone("z1"))
        updated = registry.update("z1", id="z1_renamed")
        # The registry still stores under the original key "z1"
        assert registry.get("z1") is updated
        assert updated.id == "z1_renamed"
        # The new id is NOT a separate key
        assert registry.get("z1_renamed") is None

    def test_find_at_point_zero_area_zone(self, registry: ZoneRegistry) -> None:
        """A zone with zero width or height can still contain boundary points."""
        registry.register(_make_zone("line", 10, 10, 100, 0))
        # Point on the zero-height line segment (y=10, x in [10..110])
        results = registry.find_at_point(50, 10)
        assert len(results) == 1

    def test_register_many_with_duplicate_ids_in_list(self, registry: ZoneRegistry) -> None:
        """Last zone with a duplicate ID wins within register_many."""
        z_first = _make_zone("dup", label="First")
        z_last = _make_zone("dup", label="Last")
        registry.register_many([z_first, z_last])
        assert registry.count == 1
        assert registry.get("dup").label == "Last"

    def test_remove_then_re_register(self, registry: ZoneRegistry) -> None:
        zone = _make_zone("z1")
        registry.register(zone)
        registry.remove("z1")
        assert registry.count == 0
        registry.register(zone)
        assert registry.count == 1
        assert registry.get("z1") is zone

    def test_clear_then_register(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1"))
        registry.clear()
        registry.register(_make_zone("z2"))
        assert registry.count == 1
        assert registry.get("z1") is None
        assert registry.get("z2") is not None

    def test_find_by_label_special_characters(self, registry: ZoneRegistry) -> None:
        registry.register(_make_zone("z1", label="Save & Close"))
        results = registry.find_by_label("& close")
        assert len(results) == 1

    def test_expire_stale_returns_removed_zones(self, registry: ZoneRegistry) -> None:
        old = _make_zone("old", last_seen=1.0)
        registry.register(old)
        stale = registry.expire_stale(current_time=100.0, max_age_seconds=5.0)
        assert len(stale) == 1
        assert stale[0] is old
