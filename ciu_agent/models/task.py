"""Task planning data models: steps, plans, and execution metadata.

These dataclasses are shared between the TaskPlanner (which builds plans)
and the StepExecutor (which runs individual steps).  Keeping them in the
models layer avoids circular imports between core modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskStep:
    """A single step in a task plan.

    Each step targets one zone and performs one action on it.  The
    ``action_type`` string maps to an ``ActionType`` enum value at
    execution time.

    Attributes:
        step_number: Ordinal position of this step within the plan
            (1-based).
        zone_id: Identifier of the zone to act upon.
        zone_label: Human-readable label for the target zone (used
            in logging and diagnostics).
        action_type: Action to perform.  One of ``"click"``,
            ``"double_click"``, ``"type_text"``, ``"key_press"``,
            ``"scroll"``, ``"move"``.
        parameters: Action-specific payload passed to the
            ``BrushController``.  Typical keys include ``"text"``,
            ``"key"``, ``"button"``, ``"direction"``, ``"amount"``.
        expected_change: Natural-language description of what should
            change on screen after this step completes.
        description: Human-readable summary of the step's purpose.
    """

    step_number: int
    zone_id: str
    zone_label: str
    action_type: str
    parameters: dict[str, Any] = field(default_factory=dict)
    expected_change: str = ""
    description: str = ""


@dataclass
class TaskPlan:
    """A decomposed task plan with ordered steps.

    Produced by the TaskPlanner after analysing a high-level user goal
    and the current canvas state.  Consumed by the Director to feed
    steps one-by-one into the StepExecutor.

    Attributes:
        task_description: The original high-level goal that was
            decomposed into steps.
        steps: Ordered list of ``TaskStep`` instances.
        raw_response: The raw text response from the planning API
            call (useful for debugging).
        success: Whether the planner successfully produced a valid
            plan.
        error: Human-readable error message.  Empty on success.
        api_calls_used: Number of API round-trips consumed while
            building this plan.
        latency_ms: Wall-clock time spent planning, in milliseconds.
    """

    task_description: str
    steps: list[TaskStep] = field(default_factory=list)
    raw_response: str = ""
    success: bool = False
    error: str = ""
    api_calls_used: int = 0
    latency_ms: float = 0.0
