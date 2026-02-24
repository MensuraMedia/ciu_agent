"""Director: high-level task planning and execution orchestrator.

The Director is the top-level component of the CIU Agent.  It accepts
natural-language tasks from the user, decomposes them into step sequences
via the Claude API (``TaskPlanner``), executes each step through the
``StepExecutor`` / ``BrushController`` pipeline, and handles errors by
classifying failures and re-planning when necessary.

Typical usage::

    director = Director(
        planner=planner,
        step_executor=step_executor,
        error_classifier=error_classifier,
        registry=registry,
        canvas_mapper=canvas_mapper,
        settings=settings,
    )
    result = director.execute_task("Open Notepad and type hello world")

Dependencies:
    * ``task_planner`` — decomposes tasks into steps via Claude API
    * ``step_executor`` — runs individual steps via BrushController
    * ``error_classifier`` — classifies failures, recommends recovery
    * ``zone_registry`` — current canvas state
    * ``canvas_mapper`` — for Tier 2 re-analysis on error recovery
    * ``config.settings`` — configuration
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ciu_agent.config.settings import Settings
from ciu_agent.core.error_classifier import (
    ErrorClassifier,
    RecoveryAction,
)
from ciu_agent.core.step_executor import StepExecutor, StepResult
from ciu_agent.core.task_planner import TaskPlanner
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.task import TaskPlan, TaskStep

logger = logging.getLogger(__name__)

# Maximum number of API calls per task to prevent runaway costs.
_MAX_API_CALLS: int = 30

# Maximum number of re-plan attempts before aborting.
# This covers both adaptive replans (__replan__ steps) and error replans.
_MAX_REPLANS: int = 5

# Maximum retries for a single step before escalating.
_MAX_STEP_RETRIES: int = 3



@dataclass
class TaskResult:
    """Outcome of executing a complete task.

    Attributes:
        task_description: The original high-level task.
        success: Whether the task completed successfully.
        steps_completed: Number of steps that executed successfully.
        steps_total: Total number of steps in the final plan.
        step_results: Results for each step attempted.
        plans_used: Number of plans generated (1 = no replanning).
        api_calls_used: Total API calls across planning and replanning.
        error: Human-readable error description.  Empty on success.
        duration_ms: Wall-clock time for the entire task in ms.
    """

    task_description: str
    success: bool = False
    steps_completed: int = 0
    steps_total: int = 0
    step_results: list[StepResult] = field(default_factory=list)
    plans_used: int = 0
    api_calls_used: int = 0
    error: str = ""
    duration_ms: float = 0.0


class Director:
    """Orchestrates task decomposition, execution, and error recovery.

    The Director is the main entry point for the CIU Agent.  It
    coordinates the planner, executor, and error classifier to execute
    multi-step GUI tasks end-to-end.

    All sub-components are injected via the constructor.  The Director
    itself contains no OS-specific code or API credentials.

    Args:
        planner: Task planner for Claude API decomposition.
        step_executor: Executor for individual task steps.
        error_classifier: Classifier for execution errors.
        registry: Shared zone registry (read for planning context).
        canvas_mapper: Canvas mapper for Tier 2 re-analysis.  May be
            ``None`` if re-analysis is not supported.
        recapture_fn: Optional callback that re-captures the screen and
            re-populates the zone registry.  Called between steps when
            the ``expected_change`` field suggests a major UI transition
            (e.g. an application opening).  Signature: ``() -> int``
            returning the number of zones detected.
        settings: Global configuration.
    """

    def __init__(
        self,
        planner: TaskPlanner,
        step_executor: StepExecutor,
        error_classifier: ErrorClassifier,
        registry: ZoneRegistry,
        canvas_mapper: object | None = None,
        recapture_fn: Callable[[], int] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._planner = planner
        self._step_executor = step_executor
        self._error_classifier = error_classifier
        self._registry = registry
        self._canvas_mapper = canvas_mapper
        self._recapture_fn = recapture_fn
        self._settings = settings or Settings()
        self._api_calls_used: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_task(self, task: str) -> TaskResult:
        """Execute a natural-language task end-to-end.

        Steps:

        1. Decompose the task into a plan via the Claude API.
        2. Execute each step in order through the BrushController.
        3. On ``__replan__`` steps, re-capture the screen and create a
           new plan for remaining work (adaptive replanning).
        4. On step failure, classify the error and attempt recovery
           (retry, replan, reanalyze) up to configured limits.
        5. Return a ``TaskResult`` summarising the outcome.

        Args:
            task: A natural-language description of the task to
                perform (e.g. "Open Notepad and type hello world").

        Returns:
            A ``TaskResult`` with success/failure status and details.
        """
        start_time = time.perf_counter()
        self._api_calls_used = 0
        all_step_results: list[StepResult] = []
        completed_descriptions: list[str] = []
        plans_used = 0

        # ---- Phase 1: Plan the task ----
        plan = self._create_plan(task)
        plans_used += 1

        if not plan.success:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return TaskResult(
                task_description=task,
                success=False,
                steps_total=0,
                plans_used=plans_used,
                api_calls_used=self._api_calls_used,
                error=f"Planning failed: {plan.error}",
                duration_ms=elapsed,
            )

        if not plan.steps:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return TaskResult(
                task_description=task,
                success=False,
                steps_total=0,
                plans_used=plans_used,
                api_calls_used=self._api_calls_used,
                error="Planner returned an empty plan (task may be "
                "impossible with available zones)",
                duration_ms=elapsed,
            )

        # ---- Phase 2: Execute steps ----
        current_plan = plan
        step_index = 0
        steps_completed = 0
        replan_count = 0

        while step_index < len(current_plan.steps):
            if self._api_calls_used >= _MAX_API_CALLS:
                elapsed = (time.perf_counter() - start_time) * 1000.0
                return TaskResult(
                    task_description=task,
                    success=False,
                    steps_completed=steps_completed,
                    steps_total=len(current_plan.steps),
                    step_results=all_step_results,
                    plans_used=plans_used,
                    api_calls_used=self._api_calls_used,
                    error="API call budget exhausted",
                    duration_ms=elapsed,
                )

            step = current_plan.steps[step_index]

            # ---- Handle __replan__ step (adaptive replanning) ----
            if step.zone_id == "__replan__":
                logger.info(
                    "Step %d: __replan__ — re-capturing screen and "
                    "creating new plan for remaining work",
                    step.step_number,
                )
                replan_count += 1
                if replan_count > _MAX_REPLANS:
                    elapsed = (
                        time.perf_counter() - start_time
                    ) * 1000.0
                    return TaskResult(
                        task_description=task,
                        success=False,
                        steps_completed=steps_completed,
                        steps_total=len(current_plan.steps),
                        step_results=all_step_results,
                        plans_used=plans_used,
                        api_calls_used=self._api_calls_used,
                        error="Maximum replan attempts exceeded",
                        duration_ms=elapsed,
                    )

                # Re-capture screen to detect new zones.
                self._do_recapture()

                # Create a new plan with context of completed steps.
                new_plan = self._create_plan(
                    task,
                    completed_steps=completed_descriptions,
                )
                plans_used += 1

                if not new_plan.success or not new_plan.steps:
                    elapsed = (
                        time.perf_counter() - start_time
                    ) * 1000.0
                    return TaskResult(
                        task_description=task,
                        success=False,
                        steps_completed=steps_completed,
                        steps_total=len(current_plan.steps),
                        step_results=all_step_results,
                        plans_used=plans_used,
                        api_calls_used=self._api_calls_used,
                        error="Adaptive replan failed: "
                        + new_plan.error,
                        duration_ms=elapsed,
                    )

                current_plan = new_plan
                step_index = 0
                continue

            # ---- Execute the step ----
            result = self._execute_step_with_retries(step)
            all_step_results.append(result)

            if result.success:
                steps_completed += 1
                completed_descriptions.append(step.description)
                step_index += 1
                if step_index < len(current_plan.steps):
                    # Allow the screen to update before the next step.
                    delay = self._settings.step_delay_seconds
                    if delay > 0:
                        time.sleep(delay)
                    # Re-capture screen if this step likely changed the
                    # UI significantly (app launch, dialog open, etc.).
                    self._maybe_recapture(step)
                continue

            # Step failed — classify and recover.
            recovery = self._handle_step_failure(
                result,
                replan_count,
            )

            if recovery is None:
                # Abort the task.
                elapsed = (time.perf_counter() - start_time) * 1000.0
                return TaskResult(
                    task_description=task,
                    success=False,
                    steps_completed=steps_completed,
                    steps_total=len(current_plan.steps),
                    step_results=all_step_results,
                    plans_used=plans_used,
                    api_calls_used=self._api_calls_used,
                    error=f"Step {step.step_number} failed: "
                    f"{result.error}",
                    duration_ms=elapsed,
                )

            if recovery == "replan":
                replan_count += 1
                if replan_count > _MAX_REPLANS:
                    elapsed = (
                        time.perf_counter() - start_time
                    ) * 1000.0
                    return TaskResult(
                        task_description=task,
                        success=False,
                        steps_completed=steps_completed,
                        steps_total=len(current_plan.steps),
                        step_results=all_step_results,
                        plans_used=plans_used,
                        api_calls_used=self._api_calls_used,
                        error="Maximum replan attempts exceeded",
                        duration_ms=elapsed,
                    )

                new_plan = self._create_plan(
                    task,
                    completed_steps=completed_descriptions,
                )
                plans_used += 1

                if not new_plan.success or not new_plan.steps:
                    elapsed = (
                        time.perf_counter() - start_time
                    ) * 1000.0
                    return TaskResult(
                        task_description=task,
                        success=False,
                        steps_completed=steps_completed,
                        steps_total=len(current_plan.steps),
                        step_results=all_step_results,
                        plans_used=plans_used,
                        api_calls_used=self._api_calls_used,
                        error="Replan failed: " + new_plan.error,
                        duration_ms=elapsed,
                    )

                current_plan = new_plan
                step_index = 0
                continue

            # recovery == "skip" — advance to next step.
            step_index += 1

        # All steps completed successfully.
        elapsed = (time.perf_counter() - start_time) * 1000.0
        return TaskResult(
            task_description=task,
            success=True,
            steps_completed=steps_completed,
            steps_total=len(current_plan.steps),
            step_results=all_step_results,
            plans_used=plans_used,
            api_calls_used=self._api_calls_used,
            error="",
            duration_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    @property
    def api_calls_used(self) -> int:
        """Total API calls consumed by the most recent task."""
        return self._api_calls_used

    def get_available_zones_summary(self) -> str:
        """Return a text summary of all zones in the registry.

        Returns:
            A multi-line string listing each zone's id, label,
            type, and state.
        """
        zones = self._registry.get_all()
        if not zones:
            return "(no zones detected)"
        lines: list[str] = []
        for z in zones:
            cx, cy = z.bounds.center()
            lines.append(
                f"  {z.id}: {z.label} "
                f"[{z.type.value}, {z.state.value}] "
                f"center=({cx},{cy})"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_plan(
        self,
        task: str,
        completed_steps: list[str] | None = None,
    ) -> TaskPlan:
        """Create a task plan via the planner.

        Increments the API call counter.

        Args:
            task: Natural-language task description.
            completed_steps: Optional list of already-completed step
                descriptions for adaptive replanning context.

        Returns:
            The ``TaskPlan`` from the planner.
        """
        zones = self._registry.get_all()
        plan = self._planner.plan(task, zones, completed_steps)
        self._api_calls_used += plan.api_calls_used

        # Log zone usage in the plan for debugging.
        if plan.steps:
            visual_count = sum(
                1 for s in plan.steps
                if s.zone_id not in ("__global__", "__replan__")
            )
            logger.info(
                "Plan created: %d steps (%d visual, %d global, "
                "%d replan), success=%s",
                len(plan.steps),
                visual_count,
                sum(
                    1 for s in plan.steps
                    if s.zone_id == "__global__"
                ),
                sum(
                    1 for s in plan.steps
                    if s.zone_id == "__replan__"
                ),
                plan.success,
            )
        else:
            logger.info(
                "Plan created: 0 steps, success=%s",
                plan.success,
            )
        return plan

    def _do_recapture(self) -> None:
        """Force a screen re-capture and zone re-detection.

        Calls the ``recapture_fn`` callback if available.  Used by the
        adaptive replanning logic when a ``__replan__`` step is
        encountered.
        """
        if self._recapture_fn is None:
            logger.warning(
                "Recapture requested but no recapture_fn available"
            )
            return

        logger.info("Performing screen re-capture for replanning")
        try:
            zone_count = self._recapture_fn()
            self._api_calls_used += 1
            logger.info(
                "Re-capture complete: %d zones detected", zone_count,
            )
        except Exception as exc:
            logger.error("Re-capture failed: %s", exc)

    def _execute_step_with_retries(
        self,
        step: TaskStep,
    ) -> StepResult:
        """Execute a step, retrying on transient failures.

        Uses the error classifier to decide whether to retry.
        Retries up to ``_MAX_STEP_RETRIES`` times for the same step.

        Args:
            step: The task step to execute.

        Returns:
            The final ``StepResult`` after retries are exhausted.
        """
        timestamp = time.time()
        last_result: StepResult | None = None

        for attempt in range(_MAX_STEP_RETRIES):
            result = self._step_executor.execute(step, timestamp)
            last_result = result

            if result.success:
                return result

            # Classify the error.
            classification = self._error_classifier.classify(
                error_type_str=result.error_type,
                step_description=step.description,
                attempt=attempt,
            )

            # Only retry if the classifier says RETRY.
            if classification.recovery_action != RecoveryAction.RETRY:
                return result

            logger.info(
                "Step %d: retrying (attempt %d/%d): %s",
                step.step_number,
                attempt + 1,
                _MAX_STEP_RETRIES,
                classification.description,
            )

        # All retries exhausted.
        assert last_result is not None
        return last_result

    def _handle_step_failure(
        self,
        result: StepResult,
        replan_count: int,
    ) -> str | None:
        """Determine recovery action after a step failure.

        Args:
            result: The failed step result.
            replan_count: How many replans have already occurred.

        Returns:
            One of:
            * ``"replan"`` — request a new plan from the API.
            * ``"skip"`` — skip this step and continue.
            * ``None`` — abort the task.
        """
        classification = self._error_classifier.classify(
            error_type_str=result.error_type,
            step_description=result.step.description,
            attempt=replan_count,
        )

        # Trigger Tier 2 re-analysis if recommended.
        if classification.should_reanalyze_canvas:
            self._trigger_reanalysis()

        action = classification.recovery_action

        if action == RecoveryAction.ABORT:
            logger.error(
                "Step %d: aborting task — %s",
                result.step.step_number,
                classification.description,
            )
            return None

        if action in (
            RecoveryAction.REPLAN,
            RecoveryAction.REANALYZE,
        ):
            logger.info(
                "Step %d: replanning — %s",
                result.step.step_number,
                classification.description,
            )
            return "replan"

        if action == RecoveryAction.SKIP:
            logger.info(
                "Step %d: skipping — %s",
                result.step.step_number,
                classification.description,
            )
            return "skip"

        # RETRY was already handled in _execute_step_with_retries.
        # If we get here, retries are exhausted — escalate.
        escalated = self._error_classifier.escalate(classification)
        if escalated.recovery_action == RecoveryAction.ABORT:
            return None
        return "replan"

    def _maybe_recapture(self, step: TaskStep) -> None:
        """Re-capture and re-analyse the screen if a step likely changed UI.

        Heuristic: if the step's ``expected_change`` mentions keywords
        that suggest a major state transition (window, dialog, app,
        open, launch, save), trigger a full recapture.

        Args:
            step: The just-completed task step.
        """
        if self._recapture_fn is None:
            return

        change = step.expected_change.lower()
        triggers = (
            "window", "dialog", "open", "launch", "appear",
            "application", "notepad", "save as", "menu",
        )
        if not any(keyword in change for keyword in triggers):
            return

        logger.info(
            "Step %d expected_change suggests UI transition: %r — "
            "re-capturing screen",
            step.step_number,
            step.expected_change,
        )
        try:
            zone_count = self._recapture_fn()
            self._api_calls_used += 1
            logger.info(
                "Re-capture complete: %d zones detected", zone_count,
            )
        except Exception as exc:
            logger.error("Re-capture failed: %s", exc)

    def _trigger_reanalysis(self) -> None:
        """Trigger a Tier 2 canvas re-analysis if a mapper is available.

        This is a best-effort operation.  If the canvas mapper is not
        injected or the method is not available, re-analysis is skipped
        silently.
        """
        if self._canvas_mapper is None:
            logger.warning(
                "Canvas reanalysis requested but no mapper available"
            )
            return

        # The canvas_mapper is typed as `object | None` to avoid
        # circular imports.  We duck-type the method call.
        reanalyze = getattr(self._canvas_mapper, "reanalyze", None)
        if callable(reanalyze):
            try:
                reanalyze()
                self._api_calls_used += 1
                logger.info("Tier 2 canvas re-analysis triggered")
            except Exception as exc:
                logger.error(
                    "Canvas re-analysis failed: %s", exc,
                )
        else:
            logger.warning(
                "Canvas mapper has no 'reanalyze' method"
            )

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """Human-readable summary."""
        return (
            f"Director(zones={self._registry.count}, "
            f"api_calls={self._api_calls_used})"
        )
