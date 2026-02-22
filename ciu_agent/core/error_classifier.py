"""Classifies execution errors and determines recovery strategies.

The error classifier receives information about what went wrong during
step execution and recommends a recovery strategy.  It is a pure-logic
module with no side effects: given an error type string and an attempt
counter it returns a deterministic classification that the Director can
act upon.

This module depends only on ``ciu_agent.config.settings`` and the
Python standard library.

Typical usage::

    from ciu_agent.config.settings import get_default_settings
    from ciu_agent.core.error_classifier import ErrorClassifier

    classifier = ErrorClassifier(get_default_settings())
    result = classifier.classify("timeout", step_description="click Save", attempt=0)
    if classifier.should_continue(result, attempt=0):
        # execute recovery action
        ...
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ciu_agent.config.settings import Settings


class ErrorType(Enum):
    """Classification of execution errors."""

    ZONE_NOT_FOUND = "zone_not_found"
    WRONG_ZONE = "wrong_zone"
    TIMEOUT = "timeout"
    BRUSH_LOST = "brush_lost"
    ACTION_FAILED = "action_failed"
    TASK_IMPOSSIBLE = "task_impossible"
    UNKNOWN = "unknown"


class RecoveryAction(Enum):
    """Strategy for recovering from an error."""

    RETRY = "retry"
    REPLAN = "replan"
    REANALYZE = "reanalyze"
    SKIP = "skip"
    ABORT = "abort"


@dataclass
class ErrorClassification:
    """Result of classifying an execution error.

    Attributes:
        error_type: The classified type of the error.
        recovery_action: Recommended recovery strategy.
        max_retries: How many times to retry before escalating.
        description: Human-readable explanation of the classification.
        should_reanalyze_canvas: Whether to trigger a Tier 2 canvas
            rebuild as part of recovery.
    """

    error_type: ErrorType
    recovery_action: RecoveryAction
    max_retries: int
    description: str
    should_reanalyze_canvas: bool


# Escalation order used by ``ErrorClassifier.escalate``.
_ESCALATION_ORDER: dict[RecoveryAction, RecoveryAction] = {
    RecoveryAction.RETRY: RecoveryAction.REPLAN,
    RecoveryAction.REPLAN: RecoveryAction.REANALYZE,
    RecoveryAction.REANALYZE: RecoveryAction.ABORT,
    RecoveryAction.SKIP: RecoveryAction.ABORT,
    RecoveryAction.ABORT: RecoveryAction.ABORT,
}


class ErrorClassifier:
    """Classifies execution errors and determines recovery strategies.

    The classifier is stateless: every call to ``classify`` is
    independent.  The ``attempt`` argument carries the retry history
    so the classifier can escalate on repeated failures.

    Args:
        settings: Application-wide settings.  Currently used to keep
            the constructor signature consistent with other core
            components; future versions may pull retry limits from
            settings.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # -- public API -----------------------------------------------------------

    def classify(
        self,
        error_type_str: str,
        step_description: str = "",
        attempt: int = 0,
    ) -> ErrorClassification:
        """Classify an execution error and recommend a recovery strategy.

        Args:
            error_type_str: The error type string from a ``StepResult``
                (e.g. ``"timeout"``, ``"zone_not_found"``).  An empty
                or unrecognised string is treated as ``UNKNOWN``.
            step_description: Optional human-readable description of the
                step that failed, included in the classification for
                logging purposes.
            attempt: Zero-based counter of how many times this step has
                already been attempted.  Higher values cause the
                classifier to escalate recovery severity.

        Returns:
            An ``ErrorClassification`` with the recommended recovery
            action and related metadata.
        """
        error_type = self._resolve_error_type(error_type_str)

        if error_type is ErrorType.ZONE_NOT_FOUND:
            return self._classify_zone_not_found(
                error_type, step_description, attempt,
            )
        if error_type is ErrorType.WRONG_ZONE:
            return self._classify_wrong_zone(
                error_type, step_description, attempt,
            )
        if error_type is ErrorType.TIMEOUT:
            return self._classify_timeout(
                error_type, step_description, attempt,
            )
        if error_type is ErrorType.BRUSH_LOST:
            return self._classify_brush_lost(
                error_type, step_description, attempt,
            )
        if error_type is ErrorType.ACTION_FAILED:
            return self._classify_action_failed(
                error_type, step_description, attempt,
            )
        if error_type is ErrorType.TASK_IMPOSSIBLE:
            return self._classify_task_impossible(
                error_type, step_description,
            )
        # UNKNOWN
        return self._classify_unknown(
            error_type, step_description, attempt,
        )

    def should_continue(
        self,
        classification: ErrorClassification,
        attempt: int,
    ) -> bool:
        """Decide whether the task should continue after an error.

        Args:
            classification: The result of a previous ``classify`` call.
            attempt: Current attempt counter (reserved for future use;
                the decision is based solely on the recovery action).

        Returns:
            ``True`` if the recovery action is anything other than
            ``ABORT`` -- meaning the task may still succeed.
        """
        return classification.recovery_action is not RecoveryAction.ABORT

    def escalate(
        self,
        classification: ErrorClassification,
    ) -> ErrorClassification:
        """Escalate a classification to the next severity level.

        The escalation ladder is:
        ``RETRY`` -> ``REPLAN`` -> ``REANALYZE`` -> ``ABORT``.
        ``SKIP`` escalates directly to ``ABORT``.
        ``ABORT`` remains ``ABORT`` (no change).

        Args:
            classification: The classification to escalate.

        Returns:
            A *new* ``ErrorClassification`` with the escalated action
            and an updated description.  The original classification is
            not modified.
        """
        new_action = _ESCALATION_ORDER[classification.recovery_action]
        new_reanalyze = (
            classification.should_reanalyze_canvas
            or new_action is RecoveryAction.REANALYZE
        )
        return ErrorClassification(
            error_type=classification.error_type,
            recovery_action=new_action,
            max_retries=classification.max_retries,
            description=(
                f"Escalated from {classification.recovery_action.value}"
                f" to {new_action.value}: {classification.description}"
            ),
            should_reanalyze_canvas=new_reanalyze,
        )

    # -- private helpers ------------------------------------------------------

    @staticmethod
    def _resolve_error_type(raw: str) -> ErrorType:
        """Convert a raw string to an ``ErrorType`` enum member.

        Args:
            raw: The error type string.  May be empty or unrecognised.

        Returns:
            The matching ``ErrorType``, or ``ErrorType.UNKNOWN`` if the
            string does not match any known value.
        """
        if not raw:
            return ErrorType.UNKNOWN
        try:
            return ErrorType(raw)
        except ValueError:
            return ErrorType.UNKNOWN

    @staticmethod
    def _step_ctx(step_description: str) -> str:
        """Format an optional step description for inclusion in messages."""
        if step_description:
            return f" during '{step_description}'"
        return ""

    # -- per-type classifiers -------------------------------------------------

    def _classify_zone_not_found(
        self,
        error_type: ErrorType,
        step_description: str,
        attempt: int,
    ) -> ErrorClassification:
        ctx = self._step_ctx(step_description)
        if attempt < 1:
            return ErrorClassification(
                error_type=error_type,
                recovery_action=RecoveryAction.REANALYZE,
                max_retries=1,
                description=(
                    f"Zone not found{ctx}; triggering Tier 2 canvas"
                    " rebuild and replan"
                ),
                should_reanalyze_canvas=True,
            )
        return ErrorClassification(
            error_type=error_type,
            recovery_action=RecoveryAction.ABORT,
            max_retries=1,
            description=(
                f"Zone not found{ctx} after canvas rebuild; aborting"
            ),
            should_reanalyze_canvas=False,
        )

    def _classify_wrong_zone(
        self,
        error_type: ErrorType,
        step_description: str,
        attempt: int,
    ) -> ErrorClassification:
        ctx = self._step_ctx(step_description)
        if attempt < 2:
            return ErrorClassification(
                error_type=error_type,
                recovery_action=RecoveryAction.REPLAN,
                max_retries=2,
                description=(
                    f"Canvas change mismatch{ctx}; requesting new plan"
                ),
                should_reanalyze_canvas=False,
            )
        return ErrorClassification(
            error_type=error_type,
            recovery_action=RecoveryAction.ABORT,
            max_retries=2,
            description=(
                f"Repeated canvas mismatch{ctx}; aborting"
            ),
            should_reanalyze_canvas=False,
        )

    def _classify_timeout(
        self,
        error_type: ErrorType,
        step_description: str,
        attempt: int,
    ) -> ErrorClassification:
        ctx = self._step_ctx(step_description)
        if attempt < 2:
            return ErrorClassification(
                error_type=error_type,
                recovery_action=RecoveryAction.RETRY,
                max_retries=2,
                description=(
                    f"Timed out waiting for change{ctx}; retrying"
                ),
                should_reanalyze_canvas=False,
            )
        return ErrorClassification(
            error_type=error_type,
            recovery_action=RecoveryAction.REPLAN,
            max_retries=2,
            description=(
                f"Repeated timeout{ctx}; requesting new plan"
            ),
            should_reanalyze_canvas=False,
        )

    def _classify_brush_lost(
        self,
        error_type: ErrorType,
        step_description: str,
        attempt: int,
    ) -> ErrorClassification:
        ctx = self._step_ctx(step_description)
        if attempt < 2:
            return ErrorClassification(
                error_type=error_type,
                recovery_action=RecoveryAction.RETRY,
                max_retries=2,
                description=(
                    f"Cursor not in expected position{ctx}; retrying"
                ),
                should_reanalyze_canvas=False,
            )
        return ErrorClassification(
            error_type=error_type,
            recovery_action=RecoveryAction.REANALYZE,
            max_retries=2,
            description=(
                f"Cursor repeatedly lost{ctx}; triggering Tier 2"
                " canvas rebuild"
            ),
            should_reanalyze_canvas=True,
        )

    def _classify_action_failed(
        self,
        error_type: ErrorType,
        step_description: str,
        attempt: int,
    ) -> ErrorClassification:
        ctx = self._step_ctx(step_description)
        if attempt < 1:
            return ErrorClassification(
                error_type=error_type,
                recovery_action=RecoveryAction.RETRY,
                max_retries=1,
                description=(
                    f"Platform action failed{ctx}; retrying once"
                ),
                should_reanalyze_canvas=False,
            )
        return ErrorClassification(
            error_type=error_type,
            recovery_action=RecoveryAction.REPLAN,
            max_retries=1,
            description=(
                f"Platform action failed again{ctx}; requesting"
                " new plan"
            ),
            should_reanalyze_canvas=False,
        )

    def _classify_task_impossible(
        self,
        error_type: ErrorType,
        step_description: str,
    ) -> ErrorClassification:
        ctx = self._step_ctx(step_description)
        return ErrorClassification(
            error_type=error_type,
            recovery_action=RecoveryAction.ABORT,
            max_retries=0,
            description=(
                f"Required functionality not available on screen{ctx};"
                " aborting"
            ),
            should_reanalyze_canvas=False,
        )

    def _classify_unknown(
        self,
        error_type: ErrorType,
        step_description: str,
        attempt: int,
    ) -> ErrorClassification:
        ctx = self._step_ctx(step_description)
        if attempt < 1:
            return ErrorClassification(
                error_type=error_type,
                recovery_action=RecoveryAction.RETRY,
                max_retries=1,
                description=(
                    f"Unknown error{ctx}; retrying once"
                ),
                should_reanalyze_canvas=False,
            )
        return ErrorClassification(
            error_type=error_type,
            recovery_action=RecoveryAction.ABORT,
            max_retries=1,
            description=(
                f"Unknown error{ctx} persists after retry; aborting"
            ),
            should_reanalyze_canvas=False,
        )
