"""Unit tests for the ErrorClassifier error classification and recovery module.

All tests construct ``ErrorClassification`` instances via the public API of
``ErrorClassifier``.  No mocks are needed -- this is pure-logic testing with
real ``Settings`` defaults.
"""

from __future__ import annotations

from ciu_agent.config.settings import Settings, get_default_settings
from ciu_agent.core.error_classifier import (
    ErrorClassification,
    ErrorClassifier,
    ErrorType,
    RecoveryAction,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _default_settings() -> Settings:
    """Return default Settings for most tests."""
    return get_default_settings()


def _make_classifier(settings: Settings | None = None) -> ErrorClassifier:
    """Create an ErrorClassifier with default or custom settings."""
    return ErrorClassifier(settings or _default_settings())


# ==================================================================
# Test class: Zone Not Found
# ==================================================================


class TestZoneNotFound:
    """Tests for the ZONE_NOT_FOUND classification path."""

    def test_attempt_0_returns_reanalyze(self) -> None:
        """First attempt -> REANALYZE to trigger canvas rebuild."""
        c = _make_classifier()
        result = c.classify("zone_not_found", step_description="click Save", attempt=0)
        assert result.error_type == ErrorType.ZONE_NOT_FOUND
        assert result.recovery_action == RecoveryAction.REANALYZE

    def test_attempt_0_triggers_canvas_reanalyze(self) -> None:
        """First attempt sets should_reanalyze_canvas=True."""
        c = _make_classifier()
        result = c.classify("zone_not_found", attempt=0)
        assert result.should_reanalyze_canvas is True

    def test_attempt_1_returns_abort(self) -> None:
        """Second attempt -> ABORT after canvas rebuild already tried."""
        c = _make_classifier()
        result = c.classify("zone_not_found", attempt=1)
        assert result.recovery_action == RecoveryAction.ABORT

    def test_max_retries_is_1(self) -> None:
        """max_retries is 1 for zone_not_found."""
        c = _make_classifier()
        result = c.classify("zone_not_found", attempt=0)
        assert result.max_retries == 1

    def test_description_contains_zone_not_found(self) -> None:
        """Description mentions 'Zone not found'."""
        c = _make_classifier()
        result = c.classify("zone_not_found", attempt=0)
        assert "Zone not found" in result.description


# ==================================================================
# Test class: Wrong Zone
# ==================================================================


class TestWrongZone:
    """Tests for the WRONG_ZONE classification path."""

    def test_attempt_0_returns_replan(self) -> None:
        """First attempt -> REPLAN to request a new plan."""
        c = _make_classifier()
        result = c.classify("wrong_zone", attempt=0)
        assert result.error_type == ErrorType.WRONG_ZONE
        assert result.recovery_action == RecoveryAction.REPLAN

    def test_attempt_1_still_replan(self) -> None:
        """Second attempt -> still REPLAN (under threshold of 2)."""
        c = _make_classifier()
        result = c.classify("wrong_zone", attempt=1)
        assert result.recovery_action == RecoveryAction.REPLAN

    def test_attempt_2_returns_abort(self) -> None:
        """Third attempt -> ABORT after repeated canvas mismatches."""
        c = _make_classifier()
        result = c.classify("wrong_zone", attempt=2)
        assert result.recovery_action == RecoveryAction.ABORT

    def test_should_reanalyze_canvas_is_false(self) -> None:
        """wrong_zone never sets should_reanalyze_canvas."""
        c = _make_classifier()
        for attempt in range(3):
            result = c.classify("wrong_zone", attempt=attempt)
            assert result.should_reanalyze_canvas is False


# ==================================================================
# Test class: Timeout
# ==================================================================


class TestTimeout:
    """Tests for the TIMEOUT classification path."""

    def test_attempt_0_returns_retry(self) -> None:
        """First attempt -> RETRY."""
        c = _make_classifier()
        result = c.classify("timeout", attempt=0)
        assert result.error_type == ErrorType.TIMEOUT
        assert result.recovery_action == RecoveryAction.RETRY

    def test_attempt_1_returns_retry(self) -> None:
        """Second attempt -> still RETRY (under threshold of 2)."""
        c = _make_classifier()
        result = c.classify("timeout", attempt=1)
        assert result.recovery_action == RecoveryAction.RETRY

    def test_attempt_2_returns_replan(self) -> None:
        """Third attempt -> REPLAN after repeated timeouts."""
        c = _make_classifier()
        result = c.classify("timeout", attempt=2)
        assert result.recovery_action == RecoveryAction.REPLAN

    def test_max_retries_is_2(self) -> None:
        """max_retries is 2 for timeout errors."""
        c = _make_classifier()
        result = c.classify("timeout", attempt=0)
        assert result.max_retries == 2


# ==================================================================
# Test class: Brush Lost
# ==================================================================


class TestBrushLost:
    """Tests for the BRUSH_LOST classification path."""

    def test_attempt_0_returns_retry(self) -> None:
        """First attempt -> RETRY to re-position cursor."""
        c = _make_classifier()
        result = c.classify("brush_lost", attempt=0)
        assert result.error_type == ErrorType.BRUSH_LOST
        assert result.recovery_action == RecoveryAction.RETRY

    def test_attempt_1_returns_retry(self) -> None:
        """Second attempt -> still RETRY."""
        c = _make_classifier()
        result = c.classify("brush_lost", attempt=1)
        assert result.recovery_action == RecoveryAction.RETRY

    def test_attempt_2_returns_reanalyze(self) -> None:
        """Third attempt -> REANALYZE with canvas rebuild."""
        c = _make_classifier()
        result = c.classify("brush_lost", attempt=2)
        assert result.recovery_action == RecoveryAction.REANALYZE

    def test_attempt_2_triggers_canvas_reanalyze(self) -> None:
        """Third attempt sets should_reanalyze_canvas=True."""
        c = _make_classifier()
        result = c.classify("brush_lost", attempt=2)
        assert result.should_reanalyze_canvas is True


# ==================================================================
# Test class: Action Failed
# ==================================================================


class TestActionFailed:
    """Tests for the ACTION_FAILED classification path."""

    def test_attempt_0_returns_retry(self) -> None:
        """First attempt -> RETRY once."""
        c = _make_classifier()
        result = c.classify("action_failed", attempt=0)
        assert result.error_type == ErrorType.ACTION_FAILED
        assert result.recovery_action == RecoveryAction.RETRY

    def test_attempt_1_returns_replan(self) -> None:
        """Second attempt -> REPLAN after retry failed."""
        c = _make_classifier()
        result = c.classify("action_failed", attempt=1)
        assert result.recovery_action == RecoveryAction.REPLAN

    def test_max_retries_is_1(self) -> None:
        """max_retries is 1 for action_failed errors."""
        c = _make_classifier()
        result = c.classify("action_failed", attempt=0)
        assert result.max_retries == 1


# ==================================================================
# Test class: Task Impossible
# ==================================================================


class TestTaskImpossible:
    """Tests for the TASK_IMPOSSIBLE classification path."""

    def test_always_aborts_attempt_0(self) -> None:
        """TASK_IMPOSSIBLE always ABORTs, even on first attempt."""
        c = _make_classifier()
        result = c.classify("task_impossible", attempt=0)
        assert result.error_type == ErrorType.TASK_IMPOSSIBLE
        assert result.recovery_action == RecoveryAction.ABORT

    def test_max_retries_is_0(self) -> None:
        """max_retries is 0 -- no retries for impossible tasks."""
        c = _make_classifier()
        result = c.classify("task_impossible", attempt=0)
        assert result.max_retries == 0

    def test_should_reanalyze_canvas_is_false(self) -> None:
        """task_impossible never triggers canvas reanalysis."""
        c = _make_classifier()
        result = c.classify("task_impossible", attempt=0)
        assert result.should_reanalyze_canvas is False


# ==================================================================
# Test class: Unknown Error
# ==================================================================


class TestUnknownError:
    """Tests for the UNKNOWN error classification path."""

    def test_empty_string_resolves_to_unknown(self) -> None:
        """Empty error type string maps to UNKNOWN, attempt=0 -> RETRY."""
        c = _make_classifier()
        result = c.classify("", attempt=0)
        assert result.error_type == ErrorType.UNKNOWN
        assert result.recovery_action == RecoveryAction.RETRY

    def test_attempt_1_returns_abort(self) -> None:
        """Second attempt for unknown error -> ABORT."""
        c = _make_classifier()
        result = c.classify("", attempt=1)
        assert result.recovery_action == RecoveryAction.ABORT

    def test_unrecognized_string_resolves_to_unknown(self) -> None:
        """An unrecognised error type string maps to UNKNOWN."""
        c = _make_classifier()
        result = c.classify("something_totally_unexpected", attempt=0)
        assert result.error_type == ErrorType.UNKNOWN


# ==================================================================
# Test class: should_continue
# ==================================================================


class TestShouldContinue:
    """Tests for the ``should_continue`` method."""

    def test_retry_continues(self) -> None:
        """RETRY recovery action -> should_continue returns True."""
        c = _make_classifier()
        result = c.classify("timeout", attempt=0)
        assert result.recovery_action == RecoveryAction.RETRY
        assert c.should_continue(result, attempt=0) is True

    def test_replan_continues(self) -> None:
        """REPLAN recovery action -> should_continue returns True."""
        c = _make_classifier()
        result = c.classify("wrong_zone", attempt=0)
        assert result.recovery_action == RecoveryAction.REPLAN
        assert c.should_continue(result, attempt=0) is True

    def test_reanalyze_continues(self) -> None:
        """REANALYZE recovery action -> should_continue returns True."""
        c = _make_classifier()
        result = c.classify("zone_not_found", attempt=0)
        assert result.recovery_action == RecoveryAction.REANALYZE
        assert c.should_continue(result, attempt=0) is True

    def test_abort_does_not_continue(self) -> None:
        """ABORT recovery action -> should_continue returns False."""
        c = _make_classifier()
        result = c.classify("task_impossible", attempt=0)
        assert result.recovery_action == RecoveryAction.ABORT
        assert c.should_continue(result, attempt=0) is False


# ==================================================================
# Test class: escalate
# ==================================================================


class TestEscalate:
    """Tests for the ``escalate`` method."""

    def test_retry_escalates_to_replan(self) -> None:
        """RETRY -> REPLAN on escalation."""
        c = _make_classifier()
        original = c.classify("timeout", attempt=0)
        assert original.recovery_action == RecoveryAction.RETRY
        escalated = c.escalate(original)
        assert escalated.recovery_action == RecoveryAction.REPLAN

    def test_replan_escalates_to_reanalyze(self) -> None:
        """REPLAN -> REANALYZE on escalation."""
        c = _make_classifier()
        original = c.classify("wrong_zone", attempt=0)
        assert original.recovery_action == RecoveryAction.REPLAN
        escalated = c.escalate(original)
        assert escalated.recovery_action == RecoveryAction.REANALYZE

    def test_reanalyze_escalates_to_abort(self) -> None:
        """REANALYZE -> ABORT on escalation."""
        c = _make_classifier()
        original = c.classify("zone_not_found", attempt=0)
        assert original.recovery_action == RecoveryAction.REANALYZE
        escalated = c.escalate(original)
        assert escalated.recovery_action == RecoveryAction.ABORT

    def test_skip_escalates_to_abort(self) -> None:
        """SKIP -> ABORT on escalation."""
        c = _make_classifier()
        skip_classification = ErrorClassification(
            error_type=ErrorType.UNKNOWN,
            recovery_action=RecoveryAction.SKIP,
            max_retries=0,
            description="Skipped step",
            should_reanalyze_canvas=False,
        )
        escalated = c.escalate(skip_classification)
        assert escalated.recovery_action == RecoveryAction.ABORT

    def test_abort_stays_abort(self) -> None:
        """ABORT -> ABORT (no further escalation)."""
        c = _make_classifier()
        original = c.classify("task_impossible", attempt=0)
        assert original.recovery_action == RecoveryAction.ABORT
        escalated = c.escalate(original)
        assert escalated.recovery_action == RecoveryAction.ABORT

    def test_escalated_description_mentions_escalation(self) -> None:
        """Escalated description contains 'Escalated from'."""
        c = _make_classifier()
        original = c.classify("timeout", attempt=0)
        escalated = c.escalate(original)
        assert "Escalated from" in escalated.description
        assert "retry" in escalated.description
        assert "replan" in escalated.description

    def test_escalating_to_reanalyze_sets_canvas_flag(self) -> None:
        """Escalating to REANALYZE sets should_reanalyze_canvas=True."""
        c = _make_classifier()
        original = c.classify("wrong_zone", attempt=0)
        assert original.recovery_action == RecoveryAction.REPLAN
        assert original.should_reanalyze_canvas is False
        escalated = c.escalate(original)
        assert escalated.recovery_action == RecoveryAction.REANALYZE
        assert escalated.should_reanalyze_canvas is True


# ==================================================================
# Test class: Step Description
# ==================================================================


class TestStepDescription:
    """Tests for step_description inclusion in classification output."""

    def test_step_description_appears_in_description(self) -> None:
        """Provided step_description is included in the result description."""
        c = _make_classifier()
        result = c.classify(
            "timeout",
            step_description="click Save",
            attempt=0,
        )
        assert "click Save" in result.description

    def test_empty_step_description_works(self) -> None:
        """Empty step_description produces a valid classification."""
        c = _make_classifier()
        result = c.classify("timeout", step_description="", attempt=0)
        assert result.error_type == ErrorType.TIMEOUT
        assert isinstance(result.description, str)
        assert len(result.description) > 0

    def test_long_step_description_works(self) -> None:
        """A long step_description is included without truncation."""
        c = _make_classifier()
        long_desc = "navigate to the deeply nested settings panel " * 5
        result = c.classify(
            "action_failed",
            step_description=long_desc.strip(),
            attempt=0,
        )
        assert long_desc.strip() in result.description
