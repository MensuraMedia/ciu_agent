"""Comprehensive unit tests for ciu_agent.core.director.

Tests cover successful task execution, planning failures, step failures
and recovery, API call budget enforcement, query methods, and edge
cases.  Uses MockPlanner and MockStepExecutor (no real API or brush),
real ErrorClassifier and real ZoneRegistry.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from ciu_agent.config.settings import Settings
from ciu_agent.core.director import (
    _MAX_API_CALLS,
    _MAX_REPLANS,
    Director,
    TaskResult,
)
from ciu_agent.core.error_classifier import ErrorClassifier
from ciu_agent.core.step_executor import StepResult
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.models.task import TaskPlan, TaskStep
from ciu_agent.models.zone import Rectangle, Zone, ZoneState, ZoneType

# ------------------------------------------------------------------
# Mock collaborators
# ------------------------------------------------------------------


class MockPlanner:
    """Test double for TaskPlanner.

    Returns plans from a pre-loaded list, in order.  When the list
    is exhausted, returns a failure plan.  Captures ``completed_steps``
    arguments for assertion in tests.
    """

    def __init__(self) -> None:
        self.plans: list[TaskPlan] = []
        self._call_index: int = 0
        self.completed_steps_history: list[list[str] | None] = []

    def plan(
        self,
        task: str,
        zones: list[Zone],
        completed_steps: list[str] | None = None,
    ) -> TaskPlan:
        # Store a snapshot (copy) so later mutations don't affect it.
        self.completed_steps_history.append(
            list(completed_steps) if completed_steps is not None
            else None
        )
        if self._call_index < len(self.plans):
            result = self.plans[self._call_index]
            self._call_index += 1
            return result
        return TaskPlan(
            task_description=task,
            success=False,
            error="no more plans",
        )


class MockStepExecutor:
    """Test double for StepExecutor.

    Returns results from a pre-loaded list, in order.  When the list
    is exhausted, returns a success result.
    """

    def __init__(self) -> None:
        self.results: list[StepResult] = []
        self._call_index: int = 0

    def execute(self, step: TaskStep, timestamp: float) -> StepResult:
        if self._call_index < len(self.results):
            result = self.results[self._call_index]
            self._call_index += 1
            return result
        return StepResult(
            step=step,
            success=True,
            action_result=None,
            timestamp=timestamp,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_zone(
    zone_id: str = "btn_ok",
    label: str = "OK",
    zone_type: ZoneType = ZoneType.BUTTON,
    x: int = 100,
    y: int = 200,
    width: int = 80,
    height: int = 30,
) -> Zone:
    """Create a minimal Zone for testing."""
    return Zone(
        id=zone_id,
        bounds=Rectangle(x=x, y=y, width=width, height=height),
        type=zone_type,
        label=label,
        state=ZoneState.ENABLED,
        confidence=0.95,
        last_seen=time.time(),
    )


def _make_step(
    step_number: int = 1,
    zone_id: str = "btn_ok",
    action_type: str = "click",
    description: str = "Click OK",
) -> TaskStep:
    """Create a minimal TaskStep for testing."""
    return TaskStep(
        step_number=step_number,
        zone_id=zone_id,
        zone_label="OK",
        action_type=action_type,
        parameters={},
        expected_change="Button pressed",
        description=description,
    )


def _make_success_result(step: TaskStep) -> StepResult:
    """Create a successful StepResult for testing."""
    return StepResult(
        step=step,
        success=True,
        action_result=None,
        timestamp=time.time(),
    )


def _make_failure_result(
    step: TaskStep,
    error_type: str = "action_failed",
    error: str = "Action did not complete",
) -> StepResult:
    """Create a failed StepResult for testing."""
    return StepResult(
        step=step,
        success=False,
        action_result=None,
        error=error,
        error_type=error_type,
        timestamp=time.time(),
    )


def _make_plan(
    task: str = "Click the OK button",
    steps: list[TaskStep] | None = None,
    success: bool = True,
    error: str = "",
    api_calls_used: int = 1,
) -> TaskPlan:
    """Create a TaskPlan for testing."""
    return TaskPlan(
        task_description=task,
        steps=steps or [],
        success=success,
        error=error,
        api_calls_used=api_calls_used,
    )


def _build_director(
    planner: MockPlanner | None = None,
    executor: MockStepExecutor | None = None,
    registry: ZoneRegistry | None = None,
    canvas_mapper: object | None = None,
    recapture_fn: Callable[[], int] | None = None,
) -> tuple[Director, MockPlanner, MockStepExecutor, ZoneRegistry]:
    """Build a Director with real ErrorClassifier and optional overrides."""
    settings = Settings(step_delay_seconds=0.0)
    reg = registry or ZoneRegistry()
    pl = planner or MockPlanner()
    ex = executor or MockStepExecutor()
    classifier = ErrorClassifier(settings)
    director = Director(
        planner=pl,
        step_executor=ex,
        error_classifier=classifier,
        registry=reg,
        canvas_mapper=canvas_mapper,
        recapture_fn=recapture_fn,
        settings=settings,
    )
    return director, pl, ex, reg


# ===================================================================
# 1. Successful Task Execution
# ===================================================================


class TestSuccessfulTaskExecution:
    """Tests for tasks that complete without errors."""

    def test_single_step_task_succeeds(self) -> None:
        """A single-step task with a passing step returns success."""
        director, planner, executor, _reg = _build_director()
        step = _make_step()
        planner.plans = [_make_plan(steps=[step])]
        executor.results = [_make_success_result(step)]

        result = director.execute_task("Click OK")

        assert result.success is True
        assert result.steps_completed == 1
        assert result.steps_total == 1
        assert result.error == ""

    def test_multi_step_task_all_succeed(self) -> None:
        """A multi-step task where every step succeeds."""
        director, planner, executor, _reg = _build_director()
        steps = [
            _make_step(step_number=1, description="Click File"),
            _make_step(step_number=2, description="Click Save"),
            _make_step(step_number=3, description="Click OK"),
        ]
        planner.plans = [_make_plan(steps=steps)]
        executor.results = [_make_success_result(s) for s in steps]

        result = director.execute_task("Save the file")

        assert result.success is True
        assert result.steps_completed == 3
        assert result.steps_total == 3

    def test_steps_completed_matches_successful_steps(self) -> None:
        """steps_completed equals the count of steps that succeeded."""
        director, planner, executor, _reg = _build_director()
        steps = [
            _make_step(step_number=1),
            _make_step(step_number=2),
        ]
        planner.plans = [_make_plan(steps=steps)]
        executor.results = [
            _make_success_result(steps[0]),
            _make_success_result(steps[1]),
        ]

        result = director.execute_task("Do two things")

        assert result.steps_completed == 2

    def test_plans_used_is_one_when_no_replan(self) -> None:
        """When no replan occurs, plans_used is 1."""
        director, planner, executor, _reg = _build_director()
        step = _make_step()
        planner.plans = [_make_plan(steps=[step])]
        executor.results = [_make_success_result(step)]

        result = director.execute_task("Click OK")

        assert result.plans_used == 1

    def test_api_calls_tracked(self) -> None:
        """api_calls_used reflects the planning call count."""
        director, planner, executor, _reg = _build_director()
        step = _make_step()
        planner.plans = [_make_plan(steps=[step], api_calls_used=2)]
        executor.results = [_make_success_result(step)]

        result = director.execute_task("Click OK")

        assert result.api_calls_used == 2

    def test_duration_is_positive(self) -> None:
        """duration_ms is positive for any completed task."""
        director, planner, executor, _reg = _build_director()
        step = _make_step()
        planner.plans = [_make_plan(steps=[step])]
        executor.results = [_make_success_result(step)]

        result = director.execute_task("Click OK")

        assert result.duration_ms > 0.0


# ===================================================================
# 2. Planning Failures
# ===================================================================


class TestPlanningFailures:
    """Tests for when the planner cannot produce a valid plan."""

    def test_planner_returns_failure(self) -> None:
        """Planner success=False yields TaskResult.success=False."""
        director, planner, _executor, _reg = _build_director()
        planner.plans = [
            _make_plan(success=False, error="API timeout")
        ]

        result = director.execute_task("Open Notepad")

        assert result.success is False
        assert "Planning failed" in result.error

    def test_planner_returns_empty_steps(self) -> None:
        """Planner returns success but with no steps."""
        director, planner, _executor, _reg = _build_director()
        planner.plans = [_make_plan(steps=[], success=True)]

        result = director.execute_task("Impossible task")

        assert result.success is False
        assert "empty plan" in result.error

    def test_planning_failure_tracks_api_calls(self) -> None:
        """Even a failed plan accounts for api_calls_used."""
        director, planner, _executor, _reg = _build_director()
        planner.plans = [
            _make_plan(
                success=False,
                error="API error",
                api_calls_used=3,
            )
        ]

        result = director.execute_task("Open Notepad")

        assert result.api_calls_used == 3

    def test_planning_failure_plans_used_is_one(self) -> None:
        """Even a failed plan increments plans_used to 1."""
        director, planner, _executor, _reg = _build_director()
        planner.plans = [
            _make_plan(success=False, error="fail")
        ]

        result = director.execute_task("Open Notepad")

        assert result.plans_used == 1


# ===================================================================
# 3. Step Failures and Recovery
# ===================================================================


class TestStepFailuresAndRecovery:
    """Tests for error recovery: retries, replans, and aborts."""

    def test_zone_not_found_triggers_replan(self) -> None:
        """A zone_not_found error at attempt=0 triggers replan.

        The ErrorClassifier returns REANALYZE for zone_not_found at
        attempt=0, which the Director treats as a replan.
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Click X")
        step_b = _make_step(step_number=1, description="Click Y")

        # First plan: one step that will fail.
        planner.plans = [
            _make_plan(steps=[step_a]),
            _make_plan(steps=[step_b]),
        ]

        # step_a fails with zone_not_found repeatedly (retries exhaust),
        # then replan produces step_b which succeeds.
        # _execute_step_with_retries will call execute up to 3 times
        # for step_a.  zone_not_found at attempt=0 -> REANALYZE (not
        # RETRY), so only 1 attempt occurs before returning.
        executor.results = [
            _make_failure_result(step_a, error_type="zone_not_found"),
            _make_success_result(step_b),
        ]

        result = director.execute_task("Click something")

        assert result.plans_used >= 2

    def test_action_failed_attempt_0_retries_then_replans(self) -> None:
        """action_failed at attempt=0 gets RETRY, then REPLAN.

        The classifier returns RETRY for action_failed at attempt=0.
        On second attempt (attempt=1), it returns REPLAN.
        The Director's _execute_step_with_retries will retry once,
        then _handle_step_failure triggers a replan.
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Click Save")
        step_b = _make_step(step_number=1, description="Click Save v2")

        planner.plans = [
            _make_plan(steps=[step_a]),
            _make_plan(steps=[step_b]),
        ]

        # First attempt: action_failed -> RETRY (attempt=0)
        # Second attempt: action_failed -> REPLAN (attempt=1)
        # This causes _execute_step_with_retries to return failure.
        # _handle_step_failure then triggers a replan.
        # Replan step_b succeeds.
        executor.results = [
            _make_failure_result(step_a, error_type="action_failed"),
            _make_failure_result(step_a, error_type="action_failed"),
            _make_success_result(step_b),
        ]

        result = director.execute_task("Save file")

        assert result.plans_used == 2

    def test_brush_lost_retries(self) -> None:
        """brush_lost at attempt=0 gets RETRY from the classifier.

        The Director retries the step, and the second attempt
        succeeds.
        """
        director, planner, executor, _reg = _build_director()

        step = _make_step(step_number=1, description="Click it")

        planner.plans = [_make_plan(steps=[step])]

        # First attempt: brush_lost -> RETRY (attempt=0)
        # Second attempt: success
        executor.results = [
            _make_failure_result(step, error_type="brush_lost"),
            _make_success_result(step),
        ]

        result = director.execute_task("Click it")

        assert result.success is True
        assert result.steps_completed == 1
        assert result.plans_used == 1

    def test_replan_restarts_from_step_zero(self) -> None:
        """After a replan, execution starts from step 0 of new plan."""
        director, planner, executor, _reg = _build_director()

        step_a1 = _make_step(step_number=1, description="Step A1")
        step_a2 = _make_step(step_number=2, description="Step A2")
        step_b1 = _make_step(step_number=1, description="Step B1")
        step_b2 = _make_step(step_number=2, description="Step B2")

        planner.plans = [
            _make_plan(steps=[step_a1, step_a2]),
            _make_plan(steps=[step_b1, step_b2]),
        ]

        # step_a1 succeeds, step_a2 fails (zone_not_found),
        # replan produces [step_b1, step_b2], both succeed.
        executor.results = [
            _make_success_result(step_a1),
            _make_failure_result(
                step_a2, error_type="zone_not_found"
            ),
            _make_success_result(step_b1),
            _make_success_result(step_b2),
        ]

        result = director.execute_task("Multi-step task")

        assert result.success is True
        assert result.plans_used == 2
        # step_b1 and step_b2 completed in the second plan
        assert result.steps_completed >= 2

    def test_plans_used_increments_on_replan(self) -> None:
        """Each replan increments plans_used.

        Uses ``timeout`` errors which produce RETRY inside
        _execute_step_with_retries (exhausted after 3 attempts),
        then escalate to REPLAN in _handle_step_failure.
        This allows multiple consecutive replans without early ABORT.
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Step A")
        step_b = _make_step(step_number=1, description="Step B")
        step_c = _make_step(step_number=1, description="Step C")

        planner.plans = [
            _make_plan(steps=[step_a]),
            _make_plan(steps=[step_b]),
            _make_plan(steps=[step_c]),
        ]

        # _execute_step_with_retries retries up to 3 times for
        # timeout (RETRY at attempt 0,1; REPLAN at attempt 2 exits
        # the retry loop).  Then _handle_step_failure escalates
        # RETRY -> REPLAN.
        # step_a: 3 executor calls (all timeout) -> replan
        # step_b: 3 executor calls (all timeout) -> replan
        # step_c: 1 executor call (success)
        executor.results = [
            # step_a retries (3 calls)
            _make_failure_result(step_a, error_type="timeout"),
            _make_failure_result(step_a, error_type="timeout"),
            _make_failure_result(step_a, error_type="timeout"),
            # step_b retries (3 calls)
            _make_failure_result(step_b, error_type="timeout"),
            _make_failure_result(step_b, error_type="timeout"),
            _make_failure_result(step_b, error_type="timeout"),
            # step_c succeeds
            _make_success_result(step_c),
        ]

        result = director.execute_task("Keep replanning")

        assert result.plans_used == 3

    def test_max_replans_exceeded_aborts(self) -> None:
        """Exceeding _MAX_REPLANS aborts the task.

        Uses ``timeout`` errors so each step exhausts retries and
        then escalates to REPLAN through _handle_step_failure.  After
        replan_count exceeds ``_MAX_REPLANS`` (currently 5), the
        Director aborts with "Maximum replan attempts exceeded".

        replan_count goes 0->1->2->3->4->5->6; 6 > 5 triggers abort.
        We need the initial plan + 6 replan plans = 7 plans total,
        but the 7th is never created because the limit check fires.
        So we need 6 plans and 6*3 = 18 executor calls (timeout).
        """
        director, planner, executor, _reg = _build_director()

        # Need initial plan + enough replans to exceed _MAX_REPLANS.
        # Each failed step consumes 3 executor calls (timeout retries
        # at attempt 0,1 get RETRY; attempt 2 gets REPLAN and exits).
        for i in range(_MAX_REPLANS + 2):
            s = _make_step(
                step_number=1, description=f"Step {i}"
            )
            planner.plans.append(_make_plan(steps=[s]))
            # 3 executor calls per failed step (retry loop)
            for _ in range(3):
                executor.results.append(
                    _make_failure_result(
                        s, error_type="timeout"
                    )
                )

        result = director.execute_task("Lots of replans")

        assert result.success is False
        assert "replan" in result.error.lower()

    def test_api_calls_include_replan_calls(self) -> None:
        """api_calls_used accumulates across all planning calls."""
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Step A")
        step_b = _make_step(step_number=1, description="Step B")

        planner.plans = [
            _make_plan(steps=[step_a], api_calls_used=2),
            _make_plan(steps=[step_b], api_calls_used=3),
        ]

        executor.results = [
            _make_failure_result(
                step_a, error_type="zone_not_found"
            ),
            _make_success_result(step_b),
        ]

        result = director.execute_task("Replan once")

        # 2 from first plan + 3 from second plan = 5
        assert result.api_calls_used == 5

    def test_replan_failure_aborts(self) -> None:
        """If the replan itself fails, the task aborts."""
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Step A")

        planner.plans = [
            _make_plan(steps=[step_a]),
            _make_plan(
                success=False, error="API overloaded"
            ),
        ]

        executor.results = [
            _make_failure_result(
                step_a, error_type="zone_not_found"
            ),
        ]

        result = director.execute_task("Fail replan")

        assert result.success is False
        assert "Replan failed" in result.error


# ===================================================================
# 4. API Call Budget
# ===================================================================


class TestApiCallBudget:
    """Tests for the API call budget enforcement."""

    def test_budget_exhausted_aborts(self) -> None:
        """When api_calls_used reaches _MAX_API_CALLS, task aborts."""
        director, planner, executor, _reg = _build_director()

        step = _make_step(step_number=1, description="Big step")

        # A single plan that uses all the budget.
        planner.plans = [
            _make_plan(
                steps=[step],
                api_calls_used=_MAX_API_CALLS,
            )
        ]
        # The executor would succeed, but the budget check fires
        # before executing the step.
        executor.results = [_make_success_result(step)]

        result = director.execute_task("Expensive task")

        assert result.success is False
        assert "budget exhausted" in result.error.lower()

    def test_budget_error_message(self) -> None:
        """The error message specifically mentions budget exhaustion."""
        director, planner, executor, _reg = _build_director()

        step = _make_step()
        planner.plans = [
            _make_plan(steps=[step], api_calls_used=_MAX_API_CALLS)
        ]
        executor.results = [_make_success_result(step)]

        result = director.execute_task("task")

        assert result.error == "API call budget exhausted"

    def test_budget_reports_exact_usage(self) -> None:
        """api_calls_used equals the budget limit when exhausted."""
        director, planner, executor, _reg = _build_director()

        step = _make_step()
        planner.plans = [
            _make_plan(
                steps=[step],
                api_calls_used=_MAX_API_CALLS,
            )
        ]
        executor.results = [_make_success_result(step)]

        result = director.execute_task("task")

        assert result.api_calls_used == _MAX_API_CALLS


# ===================================================================
# 5. Query Methods
# ===================================================================


class TestQueryMethods:
    """Tests for Director query/property methods."""

    def test_api_calls_used_property(self) -> None:
        """api_calls_used property reflects the most recent task."""
        director, planner, executor, _reg = _build_director()

        step = _make_step()
        planner.plans = [_make_plan(steps=[step], api_calls_used=4)]
        executor.results = [_make_success_result(step)]

        director.execute_task("Track calls")

        assert director.api_calls_used == 4

    def test_zones_summary_with_zones(self) -> None:
        """get_available_zones_summary() formats registered zones."""
        registry = ZoneRegistry()
        registry.register(
            _make_zone(
                zone_id="btn_save",
                label="Save",
                zone_type=ZoneType.BUTTON,
                x=100,
                y=200,
                width=80,
                height=30,
            )
        )
        director, _pl, _ex, _reg = _build_director(registry=registry)

        summary = director.get_available_zones_summary()

        assert "btn_save" in summary
        assert "Save" in summary
        assert "button" in summary
        assert "enabled" in summary

    def test_zones_summary_empty_registry(self) -> None:
        """get_available_zones_summary() with no zones."""
        director, _pl, _ex, _reg = _build_director()

        summary = director.get_available_zones_summary()

        assert summary == "(no zones detected)"


# ===================================================================
# 6. Edge Cases
# ===================================================================


class TestEdgeCases:
    """Tests for edge cases and special conditions."""

    def test_repr_works(self) -> None:
        """Director __repr__ returns a useful string."""
        registry = ZoneRegistry()
        registry.register(_make_zone())
        director, _pl, _ex, _reg = _build_director(registry=registry)

        text = repr(director)

        assert "Director" in text
        assert "zones=1" in text
        assert "api_calls=0" in text

    def test_canvas_mapper_none_does_not_crash(self) -> None:
        """When canvas_mapper=None, reanalysis is skipped gracefully.

        zone_not_found triggers should_reanalyze_canvas=True in the
        ErrorClassifier.  If canvas_mapper is None, the Director
        should log a warning but not crash.
        """
        director, planner, executor, _reg = _build_director(
            canvas_mapper=None,
        )

        step_a = _make_step(step_number=1, description="Step A")
        step_b = _make_step(step_number=1, description="Step B")

        planner.plans = [
            _make_plan(steps=[step_a]),
            _make_plan(steps=[step_b]),
        ]

        # zone_not_found triggers reanalyze path
        executor.results = [
            _make_failure_result(
                step_a, error_type="zone_not_found"
            ),
            _make_success_result(step_b),
        ]

        # Should not raise an exception
        result = director.execute_task("Trigger reanalysis")

        assert result.plans_used >= 2

    def test_all_steps_failing_aborts(self) -> None:
        """When a step fails irrecoverably the task aborts.

        task_impossible errors cause ABORT immediately.
        """
        director, planner, executor, _reg = _build_director()

        step = _make_step(step_number=1, description="Impossible")

        planner.plans = [_make_plan(steps=[step])]

        # task_impossible always yields ABORT, no retry.
        executor.results = [
            _make_failure_result(
                step, error_type="task_impossible"
            ),
        ]

        result = director.execute_task("Do impossible thing")

        assert result.success is False
        assert result.steps_completed == 0

    def test_director_reuse_for_multiple_tasks(self) -> None:
        """A Director can be reused across sequential tasks.

        The api_calls_used counter resets between tasks.
        """
        director, planner, executor, _reg = _build_director()

        step1 = _make_step(step_number=1, description="Task 1")
        step2 = _make_step(step_number=1, description="Task 2")

        planner.plans = [
            _make_plan(steps=[step1], api_calls_used=3),
            _make_plan(steps=[step2], api_calls_used=5),
        ]
        executor.results = [
            _make_success_result(step1),
            _make_success_result(step2),
        ]

        result1 = director.execute_task("First task")
        result2 = director.execute_task("Second task")

        assert result1.success is True
        assert result1.api_calls_used == 3

        assert result2.success is True
        assert result2.api_calls_used == 5

        # The property reflects the most recent task.
        assert director.api_calls_used == 5

    def test_task_result_dataclass_defaults(self) -> None:
        """TaskResult has correct defaults when constructed directly."""
        tr = TaskResult(task_description="test")

        assert tr.success is False
        assert tr.steps_completed == 0
        assert tr.steps_total == 0
        assert tr.step_results == []
        assert tr.plans_used == 0
        assert tr.api_calls_used == 0
        assert tr.error == ""
        assert tr.duration_ms == 0.0

    def test_canvas_mapper_with_reanalyze_method(self) -> None:
        """When canvas_mapper has a reanalyze() method, it is called.

        The Director should invoke mapper.reanalyze() and increment
        api_calls_used by 1.
        """

        class FakeMapper:
            def __init__(self) -> None:
                self.call_count: int = 0

            def reanalyze(self) -> None:
                self.call_count += 1

        mapper = FakeMapper()
        director, planner, executor, _reg = _build_director(
            canvas_mapper=mapper,
        )

        step_a = _make_step(step_number=1, description="Step A")
        step_b = _make_step(step_number=1, description="Step B")

        planner.plans = [
            _make_plan(steps=[step_a], api_calls_used=1),
            _make_plan(steps=[step_b], api_calls_used=1),
        ]

        # zone_not_found triggers reanalyze
        executor.results = [
            _make_failure_result(
                step_a, error_type="zone_not_found"
            ),
            _make_success_result(step_b),
        ]

        result = director.execute_task("Trigger mapper")

        assert mapper.call_count >= 1
        # api_calls_used includes planning calls + reanalysis
        assert result.api_calls_used >= 3

    def test_step_results_accumulated(self) -> None:
        """step_results collects all attempted step outcomes."""
        director, planner, executor, _reg = _build_director()

        steps = [
            _make_step(step_number=1, description="Click A"),
            _make_step(step_number=2, description="Click B"),
        ]
        planner.plans = [_make_plan(steps=steps)]
        r1 = _make_success_result(steps[0])
        r2 = _make_success_result(steps[1])
        executor.results = [r1, r2]

        result = director.execute_task("Two clicks")

        assert len(result.step_results) == 2

    def test_repr_after_task_execution(self) -> None:
        """repr reflects api_calls after a task is run."""
        director, planner, executor, _reg = _build_director()

        step = _make_step()
        planner.plans = [_make_plan(steps=[step], api_calls_used=7)]
        executor.results = [_make_success_result(step)]

        director.execute_task("Check repr")

        text = repr(director)
        assert "api_calls=7" in text


# ===================================================================
# 7. Adaptive Replanning (__replan__ steps)
# ===================================================================


def _make_replan_step(step_number: int = 1) -> TaskStep:
    """Create a __replan__ sentinel step for testing."""
    return TaskStep(
        step_number=step_number,
        zone_id="__replan__",
        zone_label="Replan",
        action_type="replan",
        parameters={},
        expected_change="Screen re-captured and plan updated",
        description="Re-evaluate the screen and create new plan",
    )


class TestAdaptiveReplanning:
    """Tests for the adaptive replanning feature.

    The Director supports ``__replan__`` sentinel steps.  When
    encountered, the Director re-captures the screen, creates a new
    plan with ``completed_steps`` context, and continues execution
    from step 0 of the new plan.
    """

    def test_replan_step_triggers_new_plan(self) -> None:
        """A __replan__ step causes the Director to create a new plan.

        Plan 1: [step_a, __replan__].  step_a succeeds, then the
        replan step triggers a new plan.  Plan 2: [step_b], which
        succeeds.  Overall task should succeed with plans_used == 2.
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Click File")
        replan = _make_replan_step(step_number=2)
        step_b = _make_step(step_number=1, description="Click Save")

        planner.plans = [
            _make_plan(steps=[step_a, replan]),
            _make_plan(steps=[step_b]),
        ]
        executor.results = [
            _make_success_result(step_a),
            _make_success_result(step_b),
        ]

        result = director.execute_task("File then save")

        assert result.success is True
        assert result.plans_used == 2
        assert result.steps_completed == 2

    def test_replan_step_calls_recapture_fn(self) -> None:
        """A __replan__ step invokes the recapture_fn callback.

        The Director should call ``_do_recapture()`` which calls the
        injected ``recapture_fn``.  The callback should be invoked
        exactly once per __replan__ step.
        """
        recapture_calls: list[int] = []

        def mock_recapture() -> int:
            recapture_calls.append(1)
            return 5  # 5 zones detected

        director, planner, executor, _reg = _build_director(
            recapture_fn=mock_recapture,
        )

        step_a = _make_step(step_number=1, description="Open app")
        replan = _make_replan_step(step_number=2)
        step_b = _make_step(step_number=1, description="Click new UI")

        planner.plans = [
            _make_plan(steps=[step_a, replan]),
            _make_plan(steps=[step_b]),
        ]
        executor.results = [
            _make_success_result(step_a),
            _make_success_result(step_b),
        ]

        result = director.execute_task("Open app then interact")

        assert result.success is True
        assert len(recapture_calls) == 1

    def test_replan_step_without_recapture_fn_does_not_crash(
        self,
    ) -> None:
        """When recapture_fn is None, __replan__ still works.

        The Director should log a warning but proceed with
        replanning.
        """
        director, planner, executor, _reg = _build_director(
            recapture_fn=None,
        )

        step_a = _make_step(step_number=1, description="Click X")
        replan = _make_replan_step(step_number=2)
        step_b = _make_step(step_number=1, description="Click Y")

        planner.plans = [
            _make_plan(steps=[step_a, replan]),
            _make_plan(steps=[step_b]),
        ]
        executor.results = [
            _make_success_result(step_a),
            _make_success_result(step_b),
        ]

        result = director.execute_task("Replan without recapture")

        assert result.success is True
        assert result.plans_used == 2

    def test_replan_step_passes_completed_steps_to_planner(
        self,
    ) -> None:
        """Completed step descriptions are forwarded to the planner.

        Plan 1: [step_a, step_b, __replan__].  After step_a and
        step_b succeed, the __replan__ step triggers a new plan.
        The planner should receive completed_steps=["Click File",
        "Click Edit"] for the second call.
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(
            step_number=1, description="Click File"
        )
        step_b = _make_step(
            step_number=2, description="Click Edit"
        )
        replan = _make_replan_step(step_number=3)
        step_c = _make_step(
            step_number=1, description="Click Save"
        )

        planner.plans = [
            _make_plan(steps=[step_a, step_b, replan]),
            _make_plan(steps=[step_c]),
        ]
        executor.results = [
            _make_success_result(step_a),
            _make_success_result(step_b),
            _make_success_result(step_c),
        ]

        result = director.execute_task("File, Edit, then Save")

        assert result.success is True
        # First plan call: no completed_steps (None).
        assert planner.completed_steps_history[0] is None
        # Second plan call (replan): completed_steps passed.
        assert planner.completed_steps_history[1] == [
            "Click File",
            "Click Edit",
        ]

    def test_replan_step_restarts_from_step_zero(self) -> None:
        """After __replan__, execution starts from step 0 of new plan.

        Plan 1: [step_a, __replan__], Plan 2: [step_b, step_c].
        All of step_b and step_c must execute.
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Step A")
        replan = _make_replan_step(step_number=2)
        step_b = _make_step(step_number=1, description="Step B")
        step_c = _make_step(step_number=2, description="Step C")

        planner.plans = [
            _make_plan(steps=[step_a, replan]),
            _make_plan(steps=[step_b, step_c]),
        ]
        executor.results = [
            _make_success_result(step_a),
            _make_success_result(step_b),
            _make_success_result(step_c),
        ]

        result = director.execute_task("Replan and continue")

        assert result.success is True
        # step_a + step_b + step_c = 3 completed
        assert result.steps_completed == 3
        # steps_total reflects the final plan's step count
        assert result.steps_total == 2

    def test_replan_step_failed_replan_aborts(self) -> None:
        """If the adaptive replan returns failure, the task aborts.

        Plan 1: [step_a, __replan__].  step_a succeeds, then the
        replan request fails.  Task should abort.
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Step A")
        replan = _make_replan_step(step_number=2)

        planner.plans = [
            _make_plan(steps=[step_a, replan]),
            _make_plan(
                success=False, error="Screen too complex"
            ),
        ]
        executor.results = [
            _make_success_result(step_a),
        ]

        result = director.execute_task("Replan that fails")

        assert result.success is False
        assert "Adaptive replan failed" in result.error

    def test_replan_step_empty_replan_aborts(self) -> None:
        """If the adaptive replan returns empty steps, task aborts."""
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Step A")
        replan = _make_replan_step(step_number=2)

        planner.plans = [
            _make_plan(steps=[step_a, replan]),
            _make_plan(steps=[], success=True),
        ]
        executor.results = [
            _make_success_result(step_a),
        ]

        result = director.execute_task("Replan returns empty")

        assert result.success is False
        assert "Adaptive replan failed" in result.error

    def test_multiple_replan_steps_in_sequence(self) -> None:
        """Multiple __replan__ steps trigger successive replans.

        Plan 1: [step_a, __replan__]
        Plan 2: [step_b, __replan__]
        Plan 3: [step_c]
        All succeed, plans_used == 3.
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Step A")
        replan_1 = _make_replan_step(step_number=2)
        step_b = _make_step(step_number=1, description="Step B")
        replan_2 = _make_replan_step(step_number=2)
        step_c = _make_step(step_number=1, description="Step C")

        planner.plans = [
            _make_plan(steps=[step_a, replan_1]),
            _make_plan(steps=[step_b, replan_2]),
            _make_plan(steps=[step_c]),
        ]
        executor.results = [
            _make_success_result(step_a),
            _make_success_result(step_b),
            _make_success_result(step_c),
        ]

        result = director.execute_task("Double replan")

        assert result.success is True
        assert result.plans_used == 3
        assert result.steps_completed == 3

    def test_replan_step_respects_max_replans(self) -> None:
        """__replan__ steps are limited by _MAX_REPLANS.

        If __replan__ steps cause replan_count to exceed
        _MAX_REPLANS, the task aborts.
        """
        director, planner, executor, _reg = _build_director()

        # Build _MAX_REPLANS + 2 plans, each containing a step
        # followed by a __replan__.  The last plan triggers the
        # overflow.
        for i in range(_MAX_REPLANS + 2):
            step = _make_step(
                step_number=1, description=f"Step {i}"
            )
            replan = _make_replan_step(step_number=2)
            planner.plans.append(
                _make_plan(steps=[step, replan])
            )
            executor.results.append(_make_success_result(step))

        result = director.execute_task("Replan overflow")

        assert result.success is False
        assert "replan" in result.error.lower()

    def test_replan_step_api_calls_include_recapture(self) -> None:
        """api_calls_used includes the recapture call.

        When recapture_fn is provided, each __replan__ step adds
        1 API call for the recapture plus the plan's api_calls_used.
        """
        def mock_recapture() -> int:
            return 3

        director, planner, executor, _reg = _build_director(
            recapture_fn=mock_recapture,
        )

        step_a = _make_step(step_number=1, description="Step A")
        replan = _make_replan_step(step_number=2)
        step_b = _make_step(step_number=1, description="Step B")

        planner.plans = [
            _make_plan(steps=[step_a, replan], api_calls_used=1),
            _make_plan(steps=[step_b], api_calls_used=1),
        ]
        executor.results = [
            _make_success_result(step_a),
            _make_success_result(step_b),
        ]

        result = director.execute_task("Check API calls")

        # 1 (plan 1) + 1 (recapture) + 1 (plan 2) = 3
        assert result.api_calls_used == 3

    def test_replan_step_at_start_of_plan(self) -> None:
        """A __replan__ step as the first step still works.

        Plan 1: [__replan__].  No steps completed, replan triggers.
        Plan 2: [step_a].  step_a succeeds.
        """
        director, planner, executor, _reg = _build_director()

        replan = _make_replan_step(step_number=1)
        step_a = _make_step(step_number=1, description="Step A")

        planner.plans = [
            _make_plan(steps=[replan]),
            _make_plan(steps=[step_a]),
        ]
        executor.results = [
            _make_success_result(step_a),
        ]

        result = director.execute_task("Immediate replan")

        assert result.success is True
        assert result.plans_used == 2
        # completed_steps should be empty for the replan call
        assert planner.completed_steps_history[1] == []


# ===================================================================
# 8. Completed Steps Tracking
# ===================================================================


class TestCompletedStepsTracking:
    """Tests for completed_descriptions tracking across replans.

    The Director builds a ``completed_descriptions`` list as steps
    succeed.  This list is passed to the planner on replanning so the
    API knows what work has already been done.
    """

    def test_completed_steps_none_for_initial_plan(self) -> None:
        """The initial plan receives completed_steps=None."""
        director, planner, executor, _reg = _build_director()

        step = _make_step(step_number=1, description="Click OK")
        planner.plans = [_make_plan(steps=[step])]
        executor.results = [_make_success_result(step)]

        director.execute_task("Click OK")

        assert planner.completed_steps_history[0] is None

    def test_error_replan_passes_completed_steps(self) -> None:
        """Error-based replans also pass completed_steps.

        Plan 1: [step_a, step_b].  step_a succeeds, step_b fails
        with zone_not_found -> replan.  The replan call should
        receive completed_steps=["Click File"].
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(
            step_number=1, description="Click File"
        )
        step_b = _make_step(
            step_number=2,
            zone_id="btn_missing",
            description="Click Missing",
        )
        step_c = _make_step(
            step_number=1, description="Click Found"
        )

        planner.plans = [
            _make_plan(steps=[step_a, step_b]),
            _make_plan(steps=[step_c]),
        ]
        executor.results = [
            _make_success_result(step_a),
            _make_failure_result(
                step_b, error_type="zone_not_found"
            ),
            _make_success_result(step_c),
        ]

        result = director.execute_task("Error replan test")

        assert result.success is True
        # Second plan call should have completed_steps from step_a.
        assert planner.completed_steps_history[1] == ["Click File"]

    def test_completed_steps_accumulate_across_replans(
        self,
    ) -> None:
        """Completed steps accumulate across multiple replans.

        Plan 1: [step_a, __replan__]
        Plan 2: [step_b, __replan__]
        Plan 3: [step_c]

        Replan 1 receives ["Step A"], replan 2 receives
        ["Step A", "Step B"].
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(step_number=1, description="Step A")
        replan_1 = _make_replan_step(step_number=2)
        step_b = _make_step(step_number=1, description="Step B")
        replan_2 = _make_replan_step(step_number=2)
        step_c = _make_step(step_number=1, description="Step C")

        planner.plans = [
            _make_plan(steps=[step_a, replan_1]),
            _make_plan(steps=[step_b, replan_2]),
            _make_plan(steps=[step_c]),
        ]
        executor.results = [
            _make_success_result(step_a),
            _make_success_result(step_b),
            _make_success_result(step_c),
        ]

        result = director.execute_task("Accumulating steps")

        assert result.success is True
        # Call 0 (initial plan): None
        assert planner.completed_steps_history[0] is None
        # Call 1 (first replan): ["Step A"]
        assert planner.completed_steps_history[1] == ["Step A"]
        # Call 2 (second replan): ["Step A", "Step B"]
        assert planner.completed_steps_history[2] == [
            "Step A",
            "Step B",
        ]

    def test_no_completed_steps_when_first_step_fails(
        self,
    ) -> None:
        """When the very first step fails, completed_steps is empty.

        Plan 1: [step_a].  step_a fails with zone_not_found.
        The replan call should receive completed_steps=[].
        """
        director, planner, executor, _reg = _build_director()

        step_a = _make_step(
            step_number=1, description="Click Missing"
        )
        step_b = _make_step(
            step_number=1, description="Click Found"
        )

        planner.plans = [
            _make_plan(steps=[step_a]),
            _make_plan(steps=[step_b]),
        ]
        executor.results = [
            _make_failure_result(
                step_a, error_type="zone_not_found"
            ),
            _make_success_result(step_b),
        ]

        result = director.execute_task("First step fails")

        assert result.success is True
        # Initial plan: None.
        assert planner.completed_steps_history[0] is None
        # Replan: no steps completed yet, so empty list.
        assert planner.completed_steps_history[1] == []
