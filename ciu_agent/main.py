"""CIU Agent main entry point — Phase 5 integration module.

Wires all five core components (Capture Engine, Canvas Mapper, Brush
Controller, Director, Replay Buffer) together and exposes a CLI
interface to run a complete GUI task.

Typical usage::

    python -m ciu_agent.main --task "Open Notepad and type hello world"

Programmatic usage::

    from ciu_agent.main import build_agent

    agent = build_agent(api_key="sk-ant-...")
    result = agent.run_task("Open Notepad and type hello world")
    print(result.success)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass

from ciu_agent.config.settings import Settings
from ciu_agent.core.action_executor import ActionExecutor
from ciu_agent.core.brush_controller import BrushController
from ciu_agent.core.canvas_mapper import CanvasMapper
from ciu_agent.core.capture_engine import CaptureEngine
from ciu_agent.core.director import Director, TaskResult
from ciu_agent.core.error_classifier import ErrorClassifier
from ciu_agent.core.motion_planner import MotionPlanner
from ciu_agent.core.replay_buffer import ReplayBuffer
from ciu_agent.core.state_classifier import StateClassifier
from ciu_agent.core.step_executor import StepExecutor
from ciu_agent.core.task_planner import TaskPlanner
from ciu_agent.core.tier1_analyzer import Tier1Analyzer
from ciu_agent.core.tier2_analyzer import Tier2Analyzer, Tier2Request
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.core.zone_tracker import ZoneTracker
from ciu_agent.platform.interface import PlatformInterface, create_platform

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CIU Agent
# ---------------------------------------------------------------------------


@dataclass
class CIUAgent:
    """Top-level agent that holds all component references.

    Constructed via the ``build_agent`` factory function.  Callers
    interact with the agent through ``run_task``, ``startup``, and
    ``shutdown``.

    Attributes:
        platform: OS-specific input/output driver.
        capture_engine: Continuous screen capture and Tier 0 diffing.
        registry: Shared zone registry.
        classifier: Heuristic change-type classifier.
        tier1: Local OpenCV region analyser.
        tier2: Claude API vision analyser.
        canvas_mapper: Orchestrator that routes frames through tiers.
        tracker: Cursor-to-zone spatial event tracker.
        motion_planner: Trajectory generator.
        action_executor: Zone-verified input action executor.
        brush: High-level cursor/action controller.
        task_planner: Claude API task decomposer.
        step_executor: TaskStep-to-BrushController bridge.
        error_classifier: Failure classification and recovery.
        director: Top-level task orchestrator.
        replay: Session recording buffer.
        settings: Immutable application configuration.
    """

    platform: PlatformInterface
    capture_engine: CaptureEngine
    registry: ZoneRegistry
    classifier: StateClassifier
    tier1: Tier1Analyzer
    tier2: Tier2Analyzer
    canvas_mapper: CanvasMapper
    tracker: ZoneTracker
    motion_planner: MotionPlanner
    action_executor: ActionExecutor
    brush: BrushController
    task_planner: TaskPlanner
    step_executor: StepExecutor
    error_classifier: ErrorClassifier
    director: Director
    replay: ReplayBuffer
    settings: Settings

    # -- Session state (not part of the dataclass equality) ----------------

    def __post_init__(self) -> None:
        """Initialize mutable session state."""
        self._replay_active: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def startup(self) -> None:
        """Perform initial capture and Tier 2 analysis to populate zones.

        Captures the first frame, sends it directly to the Tier 2
        analyser (bypassing the StateClassifier's stability-wait
        logic), and replaces the zone registry with the API response.

        After this method returns the zone registry is populated and
        the Director is ready to execute tasks.
        """
        logger.info("Starting initial capture and Tier 2 analysis")

        # 1. Capture initial frame.
        frame = self.capture_engine.capture_to_buffer()
        h, w = frame.image.shape[:2]
        logger.info("Initial frame captured: %dx%d", w, h)

        # 2. Encode and send directly to Tier 2 (bypass classifier
        #    which would set should_wait=True for 100% change).
        image_data = Tier2Analyzer.encode_frame(frame.image)
        request = Tier2Request(
            image_data=image_data,
            screen_width=w,
            screen_height=h,
            context="Initial full-screen analysis on startup.",
        )
        response = self.tier2.analyze_sync(request)

        if response.success:
            self.registry.replace_all(response.zones)
            logger.info(
                "Initial Tier 2 analysis: %d zones detected "
                "(%.0f ms, %d tokens)",
                len(response.zones),
                response.latency_ms,
                response.token_count,
            )
        else:
            logger.warning(
                "Initial Tier 2 analysis failed: %s",
                response.error,
            )

    def shutdown(self) -> None:
        """Stop the replay session if one is active.

        Safe to call multiple times; subsequent calls are no-ops.
        """
        if self._replay_active:
            try:
                session_dir = self.replay.stop_session()
                self._replay_active = False
                logger.info(
                    "Replay session saved to %s", session_dir,
                )
            except RuntimeError:
                # No active session — already stopped.
                self._replay_active = False

    def run_task(self, task: str) -> TaskResult:
        """Execute a natural-language task end-to-end.

        Full sequence:

        1. Start a replay session.
        2. Capture the initial frame and run Tier 2 analysis.
        3. Record the initial frame in the replay buffer.
        4. Hand the task to the Director for step-by-step execution.
        5. Stop the replay session.
        6. Return the ``TaskResult``.

        Args:
            task: Natural-language description of the task to perform
                (e.g. "Open Notepad and type hello world").

        Returns:
            A ``TaskResult`` describing the outcome, including success
            status, steps completed, and timing information.
        """
        # 1. Start replay session.
        screen_size = self.platform.get_screen_size()
        session_id = self.replay.start_session(
            task_description=task,
            screen_size=screen_size,
        )
        self._replay_active = True
        logger.info("Replay session started: %s", session_id)

        try:
            # 2. Initial capture + Tier 2 analysis.
            self.startup()

            # 3. Record the initial frame.
            initial_frame = self.capture_engine.get_latest_frame()
            if initial_frame is not None:
                self.replay.record_frame(
                    image=initial_frame.image,
                    cursor_x=initial_frame.cursor_x,
                    cursor_y=initial_frame.cursor_y,
                    timestamp=initial_frame.timestamp,
                    frame_number=initial_frame.frame_number,
                )

            # 4. Execute the task via the Director.
            logger.info("Executing task: %s", task)
            result = self.director.execute_task(task)

            logger.info(
                "Task %s: %d/%d steps completed in %.1f ms "
                "(%d API calls, %d plans)",
                "succeeded" if result.success else "failed",
                result.steps_completed,
                result.steps_total,
                result.duration_ms,
                result.api_calls_used,
                result.plans_used,
            )

            return result

        finally:
            # 5. Stop replay session (always, even on exception).
            self.shutdown()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_agent(
    api_key: str,
    settings: Settings | None = None,
) -> CIUAgent:
    """Create all components and return a fully wired ``CIUAgent``.

    Instantiates every component in dependency order and injects them
    into one another.  The returned agent is ready to call ``run_task``.

    Args:
        api_key: Anthropic API key for Tier 2 analysis and task
            planning.
        settings: Optional settings override.  When ``None`` the
            default settings are used.

    Returns:
        A fully constructed ``CIUAgent`` instance.
    """
    if settings is None:
        settings = Settings()

    # 1. Platform
    platform = create_platform()
    logger.info("Platform: %s", platform.get_platform_name())

    # 2. Capture Engine
    capture_engine = CaptureEngine(platform, settings)

    # 3. Zone Registry
    registry = ZoneRegistry()

    # 4. State Classifier
    classifier = StateClassifier(settings)

    # 5. Tier 1 Analyzer
    tier1 = Tier1Analyzer(settings)

    # 6. Tier 2 Analyzer
    tier2 = Tier2Analyzer(settings, api_key=api_key)

    # 7. Canvas Mapper
    canvas_mapper = CanvasMapper(
        settings=settings,
        registry=registry,
        classifier=classifier,
        tier1=tier1,
        tier2=tier2,
    )

    # 8. Zone Tracker
    tracker = ZoneTracker(registry, settings)

    # 9. Motion Planner
    motion_planner = MotionPlanner(registry, settings)

    # 10. Action Executor
    action_executor = ActionExecutor(platform, registry, settings)

    # 11. Brush Controller
    brush = BrushController(
        platform=platform,
        registry=registry,
        tracker=tracker,
        planner=motion_planner,
        executor=action_executor,
        settings=settings,
    )

    # 12. Task Planner
    task_planner = TaskPlanner(
        settings,
        api_key=api_key,
        platform_name=platform.get_platform_name(),
    )

    # 13. Step Executor
    step_executor = StepExecutor(
        brush=brush,
        registry=registry,
        platform=platform,
        settings=settings,
    )

    # 14. Error Classifier
    error_classifier = ErrorClassifier(settings)

    # 15. Recapture callback for Director screen re-analysis.
    def _recapture() -> int:
        """Re-capture the screen and update the zone registry."""
        frame = capture_engine.capture_to_buffer()
        h, w = frame.image.shape[:2]
        image_data = Tier2Analyzer.encode_frame(frame.image)
        req = Tier2Request(
            image_data=image_data,
            screen_width=w,
            screen_height=h,
            context="Re-analysis after UI state change.",
        )
        resp = tier2.analyze_sync(req)
        if resp.success:
            registry.replace_all(resp.zones)
            return len(resp.zones)
        logger.warning("Re-capture Tier 2 failed: %s", resp.error)
        return registry.count

    # 16. Director
    director = Director(
        planner=task_planner,
        step_executor=step_executor,
        error_classifier=error_classifier,
        registry=registry,
        canvas_mapper=canvas_mapper,
        recapture_fn=_recapture,
        settings=settings,
    )

    # 17. Replay Buffer
    replay = ReplayBuffer(settings)

    return CIUAgent(
        platform=platform,
        capture_engine=capture_engine,
        registry=registry,
        classifier=classifier,
        tier1=tier1,
        tier2=tier2,
        canvas_mapper=canvas_mapper,
        tracker=tracker,
        motion_planner=motion_planner,
        action_executor=action_executor,
        brush=brush,
        task_planner=task_planner,
        step_executor=step_executor,
        error_classifier=error_classifier,
        director=director,
        replay=replay,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments, build the agent, run the task, and print results."""
    parser = argparse.ArgumentParser(
        prog="ciu_agent",
        description=(
            "CIU Agent -- Complete Interface Usage Agent. "
            "Execute GUI tasks via natural language."
        ),
    )
    parser.add_argument(
        "--task",
        "-t",
        required=True,
        help="The task to execute (e.g. 'Open Notepad and type hello').",
    )
    parser.add_argument(
        "--api-key",
        "-k",
        default="",
        help=(
            "Anthropic API key. Falls back to the ANTHROPIC_API_KEY "
            "environment variable if not provided."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()

    # -- Logging setup ---------------------------------------------------
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # -- Resolve API key -------------------------------------------------
    api_key: str = args.api_key or os.environ.get(
        "ANTHROPIC_API_KEY", "",
    )
    if not api_key:
        logger.error(
            "No API key provided. Use --api-key or set the "
            "ANTHROPIC_API_KEY environment variable."
        )
        sys.exit(1)

    # -- Build and run ---------------------------------------------------
    logger.info("Building CIU Agent")
    agent = build_agent(api_key=api_key)

    logger.info("Running task: %s", args.task)
    result = agent.run_task(args.task)

    # -- Print result summary --------------------------------------------
    _print_result_summary(result)

    sys.exit(0 if result.success else 1)


def _print_result_summary(result: TaskResult) -> None:
    """Print a human-readable summary of the task result.

    Args:
        result: The ``TaskResult`` returned by the agent.
    """
    separator = "-" * 60
    print(separator)
    print(f"Task:       {result.task_description}")
    print(f"Status:     {'SUCCESS' if result.success else 'FAILED'}")
    print(
        f"Steps:      {result.steps_completed}/{result.steps_total} "
        f"completed"
    )
    print(f"Plans used: {result.plans_used}")
    print(f"API calls:  {result.api_calls_used}")
    print(f"Duration:   {result.duration_ms:.0f} ms")
    if result.error:
        print(f"Error:      {result.error}")
    print(separator)


if __name__ == "__main__":
    main()
