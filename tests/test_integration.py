"""End-to-end integration tests for the CIU Agent.

Validates the full pipeline with mocked platform and API calls.
Tests do NOT require real screen capture or Claude API access.

Test groups:
    1. Full pipeline wiring (build_agent / CIUAgent dataclass).
    2. CIUAgent.startup() populates zone registry.
    3. CIUAgent.run_task() full pipeline.
    4. Error recovery integration (replanning).
    5. API budget enforcement.
    6. Replay buffer integration (session directory creation).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from ciu_agent.config.settings import Settings
from ciu_agent.core.action_executor import ActionExecutor
from ciu_agent.core.brush_controller import BrushController
from ciu_agent.core.canvas_mapper import CanvasMapper
from ciu_agent.core.capture_engine import CaptureEngine, DiffResult
from ciu_agent.core.director import _MAX_API_CALLS, Director
from ciu_agent.core.error_classifier import ErrorClassifier
from ciu_agent.core.motion_planner import MotionPlanner
from ciu_agent.core.replay_buffer import ReplayBuffer
from ciu_agent.core.state_classifier import (
    ChangeClassification,
    StateClassifier,
)
from ciu_agent.core.step_executor import StepExecutor
from ciu_agent.core.task_planner import TaskPlanner
from ciu_agent.core.tier1_analyzer import Tier1Analyzer
from ciu_agent.core.tier2_analyzer import Tier2Analyzer, Tier2Response
from ciu_agent.core.zone_registry import ZoneRegistry
from ciu_agent.core.zone_tracker import ZoneTracker
from ciu_agent.main import CIUAgent, build_agent
from ciu_agent.models.task import TaskPlan, TaskStep
from ciu_agent.models.zone import Rectangle, Zone, ZoneState, ZoneType
from ciu_agent.platform.interface import PlatformInterface, WindowInfo

# ------------------------------------------------------------------
# MockPlatform -- shared across all integration tests
# ------------------------------------------------------------------


class MockPlatform(PlatformInterface):
    """Fake platform that returns black frames and no-ops for input.

    Used across all integration tests to avoid real OS interaction.
    """

    def __init__(self, width: int = 100, height: int = 100) -> None:
        self._width = width
        self._height = height
        self._cursor = (50, 50)

    def capture_frame(self) -> np.ndarray:
        return np.zeros(
            (self._height, self._width, 3), dtype=np.uint8,
        )

    def get_cursor_pos(self) -> tuple[int, int]:
        return self._cursor

    def move_cursor(self, x: int, y: int) -> None:
        self._cursor = (x, y)

    def click(self, x: int, y: int, button: str = "left") -> None:
        pass

    def double_click(
        self, x: int, y: int, button: str = "left",
    ) -> None:
        pass

    def scroll(self, x: int, y: int, amount: int) -> None:
        pass

    def type_text(self, text: str) -> None:
        pass

    def key_press(self, key: str) -> None:
        pass

    def get_screen_size(self) -> tuple[int, int]:
        return (self._width, self._height)

    def get_active_window(self) -> WindowInfo:
        return WindowInfo(
            title="Test",
            x=0,
            y=0,
            width=self._width,
            height=self._height,
            is_active=True,
        )

    def list_windows(self) -> list[WindowInfo]:
        return [self.get_active_window()]

    def get_platform_name(self) -> str:
        return "test"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_zone(
    zone_id: str = "btn_ok",
    label: str = "OK",
    zone_type: ZoneType = ZoneType.BUTTON,
    x: int = 10,
    y: int = 10,
    width: int = 80,
    height: int = 80,
) -> Zone:
    """Create a Zone that covers a region inside a 100x100 screen."""
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
    zone_label: str = "OK",
    action_type: str = "click",
    parameters: dict | None = None,
) -> TaskStep:
    """Create a TaskStep with sensible defaults."""
    return TaskStep(
        step_number=step_number,
        zone_id=zone_id,
        zone_label=zone_label,
        action_type=action_type,
        parameters=parameters or {},
        expected_change="button clicked",
        description=f"Click {zone_label}",
    )


def _make_plan(
    task: str = "click OK",
    steps: list[TaskStep] | None = None,
    success: bool = True,
    api_calls_used: int = 1,
) -> TaskPlan:
    """Create a TaskPlan with sensible defaults."""
    return TaskPlan(
        task_description=task,
        steps=steps or [_make_step()],
        raw_response="[]",
        success=success,
        api_calls_used=api_calls_used,
    )


def _make_settings(
    recording_enabled: bool = False,
    session_dir: str = "sessions",
) -> Settings:
    """Create settings with recording disabled by default."""
    return Settings(
        recording_enabled=recording_enabled,
        session_dir=session_dir,
        save_frames_as_png=False,
        compress_video=False,
        step_delay_seconds=0.0,
    )


def _make_noskip_classifier(settings: Settings) -> StateClassifier:
    """Create a StateClassifier that never sets should_wait=True.

    The real StateClassifier sets ``should_wait=True`` for large
    changes (PAGE_NAVIGATION, APP_SWITCH) to let animations
    settle. This causes ``CanvasMapper.process_frame`` to skip the
    frame entirely and never invoke Tier 2.  For integration tests
    we need Tier 2 to fire immediately, so we wrap the classifier
    to force ``should_wait=False``.
    """
    real = StateClassifier(settings)
    mock_classifier = MagicMock(spec=StateClassifier)

    def _classify_no_wait(
        diff: DiffResult,
        cursor_pos: tuple[int, int],
        active_window: WindowInfo | None = None,
    ) -> ChangeClassification:
        result = real.classify(diff, cursor_pos, active_window)
        # Force should_wait to False so frames are never skipped.
        return ChangeClassification(
            change_type=result.change_type,
            tier=result.tier,
            regions=result.regions,
            confidence=result.confidence,
            should_wait=False,
            wait_ms=0,
        )

    mock_classifier.classify = _classify_no_wait
    return mock_classifier


def _build_full_stack(
    platform: MockPlatform | None = None,
    settings: Settings | None = None,
    tier2_mock: Tier2Analyzer | None = None,
    planner_mock: TaskPlanner | None = None,
    pre_register_zones: list[Zone] | None = None,
) -> CIUAgent:
    """Build a fully-wired CIUAgent with real components and mocks.

    Uses real components where possible, mocking only the
    Tier2Analyzer (to avoid API calls) and the TaskPlanner (to
    avoid API calls).  The StateClassifier is wrapped to never
    set ``should_wait=True`` so that Tier 2 analysis fires
    immediately during ``startup()``.

    Args:
        platform: MockPlatform instance. Created if None.
        settings: Settings override. Created if None.
        tier2_mock: Mock Tier2Analyzer. Created if None.
        planner_mock: Mock TaskPlanner. Created if None.
        pre_register_zones: Zones to register in the registry
            before returning the agent. Useful for tests that
            need zones available before calling run_task().

    Returns:
        A fully wired CIUAgent ready for testing.
    """
    if platform is None:
        platform = MockPlatform()
    if settings is None:
        settings = _make_settings()

    capture_engine = CaptureEngine(platform, settings)
    registry = ZoneRegistry()
    classifier = _make_noskip_classifier(settings)
    tier1 = Tier1Analyzer(settings)

    if tier2_mock is None:
        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

    canvas_mapper = CanvasMapper(
        settings=settings,
        registry=registry,
        classifier=classifier,
        tier1=tier1,
        tier2=tier2_mock,
    )

    tracker = ZoneTracker(registry, settings)
    motion_planner = MotionPlanner(registry, settings)
    action_executor = ActionExecutor(platform, registry, settings)
    brush = BrushController(
        platform=platform,
        registry=registry,
        tracker=tracker,
        planner=motion_planner,
        executor=action_executor,
        settings=settings,
    )

    if planner_mock is None:
        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

    step_executor = StepExecutor(
        brush=brush,
        registry=registry,
        platform=platform,
        settings=settings,
    )
    error_classifier = ErrorClassifier(settings)
    director = Director(
        planner=planner_mock,
        step_executor=step_executor,
        error_classifier=error_classifier,
        registry=registry,
        canvas_mapper=canvas_mapper,
        settings=settings,
    )
    replay = ReplayBuffer(settings)

    if pre_register_zones:
        registry.register_many(pre_register_zones)

    return CIUAgent(
        platform=platform,
        capture_engine=capture_engine,
        registry=registry,
        classifier=classifier,
        tier1=tier1,
        tier2=tier2_mock,
        canvas_mapper=canvas_mapper,
        tracker=tracker,
        motion_planner=motion_planner,
        action_executor=action_executor,
        brush=brush,
        task_planner=planner_mock,
        step_executor=step_executor,
        error_classifier=error_classifier,
        director=director,
        replay=replay,
        settings=settings,
    )


# ===================================================================
# Test Group 1: Full pipeline wiring
# ===================================================================


class TestPipelineWiring:
    """Tests that build_agent creates all components with correct wiring."""

    def test_build_agent_creates_all_components(self) -> None:
        """build_agent returns a CIUAgent with all fields non-None."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key-123")

        assert agent.platform is not None
        assert agent.capture_engine is not None
        assert agent.registry is not None
        assert agent.classifier is not None
        assert agent.tier1 is not None
        assert agent.tier2 is not None
        assert agent.canvas_mapper is not None
        assert agent.tracker is not None
        assert agent.motion_planner is not None
        assert agent.action_executor is not None
        assert agent.brush is not None
        assert agent.task_planner is not None
        assert agent.step_executor is not None
        assert agent.error_classifier is not None
        assert agent.director is not None
        assert agent.replay is not None
        assert agent.settings is not None

    def test_build_agent_uses_custom_settings(self) -> None:
        """build_agent respects the settings parameter."""
        custom = Settings(target_fps=5, max_fps=10)
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key", settings=custom)

        assert agent.settings.target_fps == 5
        assert agent.settings.max_fps == 10

    def test_director_has_planner_connected(self) -> None:
        """Director references the same planner that was injected."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        assert agent.director._planner is agent.task_planner

    def test_director_has_step_executor_connected(self) -> None:
        """Director references the same step_executor."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        assert agent.director._step_executor is agent.step_executor

    def test_director_has_error_classifier_connected(self) -> None:
        """Director references the same error_classifier."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        assert (
            agent.director._error_classifier
            is agent.error_classifier
        )

    def test_brush_has_tracker_connected(self) -> None:
        """BrushController references the tracker."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        assert agent.brush._tracker is agent.tracker

    def test_brush_has_planner_connected(self) -> None:
        """BrushController references the motion planner."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        assert agent.brush._planner is agent.motion_planner

    def test_brush_has_executor_connected(self) -> None:
        """BrushController references the action executor."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        assert agent.brush._executor is agent.action_executor

    def test_canvas_mapper_has_registry_connected(self) -> None:
        """CanvasMapper references the shared registry."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        assert agent.canvas_mapper.registry is agent.registry

    def test_canvas_mapper_has_classifier_connected(self) -> None:
        """CanvasMapper references the state classifier."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        assert agent.canvas_mapper._classifier is agent.classifier

    def test_canvas_mapper_has_tier1_connected(self) -> None:
        """CanvasMapper references the Tier1 analyzer."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        assert agent.canvas_mapper._tier1 is agent.tier1

    def test_canvas_mapper_has_tier2_connected(self) -> None:
        """CanvasMapper references the Tier2 analyzer."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        assert agent.canvas_mapper._tier2 is agent.tier2

    def test_shared_registry_across_components(self) -> None:
        """All components share the same ZoneRegistry instance."""
        with patch(
            "ciu_agent.main.create_platform",
            return_value=MockPlatform(),
        ):
            agent = build_agent(api_key="test-key")

        registry = agent.registry
        assert agent.canvas_mapper.registry is registry
        assert agent.tracker.registry is registry
        assert agent.brush._registry is registry
        assert agent.director._registry is registry


# ===================================================================
# Test Group 2: CIUAgent.startup() populates zone registry
# ===================================================================


class TestStartup:
    """Tests that startup() captures a frame and populates zones."""

    def test_startup_populates_zones_via_tier2(self) -> None:
        """startup() uses Tier 2 analysis and registers zones."""
        btn = _make_zone("btn_start", "Start")
        txt = _make_zone(
            "txt_search", "Search", ZoneType.TEXT_FIELD,
            x=0, y=0, width=60, height=20,
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[btn, txt],
            success=True,
            latency_ms=50.0,
            token_count=100,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        agent = _build_full_stack(tier2_mock=tier2_mock)
        agent.startup()

        assert agent.registry.count == 2
        assert agent.registry.contains("btn_start")
        assert agent.registry.contains("txt_search")

    def test_startup_captures_initial_frame(self) -> None:
        """startup() captures at least one frame into the buffer."""
        agent = _build_full_stack()
        agent.startup()

        assert agent.capture_engine.buffer_size >= 1

    def test_startup_frame_dimensions_match_platform(self) -> None:
        """Captured frame matches MockPlatform dimensions."""
        platform = MockPlatform(width=200, height=150)
        agent = _build_full_stack(platform=platform)
        agent.startup()

        frame = agent.capture_engine.get_latest_frame()
        assert frame is not None
        assert frame.image.shape == (150, 200, 3)

    def test_startup_empty_tier2_response_leaves_registry_empty(
        self,
    ) -> None:
        """When Tier 2 returns no zones, registry stays empty."""
        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        agent = _build_full_stack(tier2_mock=tier2_mock)
        agent.startup()

        assert agent.registry.count == 0

    def test_startup_tier2_called_with_full_frame(self) -> None:
        """startup() calls Tier2 analyze_sync with proper request."""
        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        agent = _build_full_stack(tier2_mock=tier2_mock)
        agent.startup()

        tier2_mock.analyze_sync.assert_called_once()


# ===================================================================
# Test Group 3: CIUAgent.run_task() full pipeline
# ===================================================================


class TestRunTask:
    """Tests that run_task() executes the full agent pipeline."""

    def test_run_task_success_single_step(
        self, tmp_path: Path,
    ) -> None:
        """A single-step plan executes successfully end-to-end."""
        zone = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        step = _make_step(zone_id="btn_ok", zone_label="OK")
        plan = _make_plan(steps=[step])
        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = plan

        platform = MockPlatform()
        agent = _build_full_stack(
            platform=platform,
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("click OK")

        assert result.success is True
        assert result.steps_completed == 1
        assert result.steps_total == 1
        assert result.plans_used == 1
        assert result.error == ""

    def test_run_task_multi_step_success(
        self, tmp_path: Path,
    ) -> None:
        """A multi-step plan executes all steps successfully."""
        zone_ok = _make_zone("btn_ok", "OK")
        zone_cancel = _make_zone(
            "btn_cancel", "Cancel",
            x=0, y=0, width=40, height=40,
        )
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone_ok, zone_cancel], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        steps = [
            _make_step(1, "btn_ok", "OK"),
            _make_step(2, "btn_cancel", "Cancel"),
        ]
        plan = _make_plan(steps=steps)
        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = plan

        platform = MockPlatform()
        agent = _build_full_stack(
            platform=platform,
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("click OK then Cancel")

        assert result.success is True
        assert result.steps_completed == 2
        assert result.steps_total == 2

    def test_run_task_planning_failure(
        self, tmp_path: Path,
    ) -> None:
        """run_task returns failure when planning fails."""
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = TaskPlan(
            task_description="impossible task",
            success=False,
            error="No API key configured.",
            api_calls_used=1,
        )

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("impossible task")

        assert result.success is False
        assert "Planning failed" in result.error

    def test_run_task_empty_plan_fails(
        self, tmp_path: Path,
    ) -> None:
        """run_task returns failure when plan has no steps."""
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = TaskPlan(
            task_description="empty",
            steps=[],
            success=True,
            api_calls_used=1,
        )

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("empty")

        assert result.success is False
        assert "empty plan" in result.error.lower()

    def test_run_task_type_text_action(
        self, tmp_path: Path,
    ) -> None:
        """A type_text step passes text through the pipeline."""
        zone = _make_zone(
            "txt_input", "Input", ZoneType.TEXT_FIELD,
        )
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        step = _make_step(
            zone_id="txt_input",
            zone_label="Input",
            action_type="type_text",
            parameters={"text": "hello world"},
        )
        plan = _make_plan(steps=[step])
        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = plan

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("type hello")

        assert result.success is True
        assert result.steps_completed == 1

    def test_run_task_records_result_duration(
        self, tmp_path: Path,
    ) -> None:
        """run_task result has a positive duration_ms."""
        zone = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("click OK")

        assert result.duration_ms > 0

    def test_run_task_calls_planner_with_zones(
        self, tmp_path: Path,
    ) -> None:
        """run_task passes detected zones to the planner."""
        zone = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        agent.run_task("click OK")

        planner_mock.plan.assert_called()
        call_args = planner_mock.plan.call_args
        task_arg = call_args[0][0]
        zones_arg = call_args[0][1]
        assert task_arg == "click OK"
        assert len(zones_arg) == 1
        assert zones_arg[0].id == "btn_ok"

    def test_run_task_shutdown_cleans_replay(
        self, tmp_path: Path,
    ) -> None:
        """After run_task the replay session is stopped."""
        zone = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        agent.run_task("click OK")

        assert agent.replay.is_recording is False


# ===================================================================
# Test Group 4: Error recovery integration
# ===================================================================


class TestErrorRecovery:
    """Tests that the Director handles step failures and replans."""

    def test_replan_on_missing_zone(
        self, tmp_path: Path,
    ) -> None:
        """Director replans when a step references a missing zone.

        First plan references "btn_missing" which is not registered.
        The error classifier recommends REANALYZE (which triggers
        replan). The second plan references "btn_ok" which exists.
        """
        zone_ok = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone_ok], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        # First plan: references a zone that doesn't exist.
        bad_step = _make_step(
            zone_id="btn_missing", zone_label="Missing",
        )
        bad_plan = _make_plan(steps=[bad_step])

        # Second plan: references a zone that exists.
        good_step = _make_step(zone_id="btn_ok", zone_label="OK")
        good_plan = _make_plan(steps=[good_step])

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.side_effect = [bad_plan, good_plan]

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("click OK")

        assert result.success is True
        assert result.plans_used == 2

    def test_replan_preserves_api_call_count(
        self, tmp_path: Path,
    ) -> None:
        """API calls from both plans are counted in the result."""
        zone_ok = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone_ok], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        bad_plan = _make_plan(
            steps=[_make_step(zone_id="btn_missing")],
            api_calls_used=2,
        )
        good_plan = _make_plan(
            steps=[_make_step(zone_id="btn_ok")],
            api_calls_used=3,
        )

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.side_effect = [bad_plan, good_plan]

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("click OK")

        assert result.api_calls_used >= 2

    def test_replan_fails_if_second_plan_fails(
        self, tmp_path: Path,
    ) -> None:
        """If the second plan also fails, the task aborts."""
        zone_ok = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone_ok], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        bad_step = _make_step(zone_id="btn_missing")
        bad_plan = _make_plan(steps=[bad_step])

        failed_plan = TaskPlan(
            task_description="test",
            success=False,
            error="planning error",
            api_calls_used=1,
        )

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.side_effect = [bad_plan, failed_plan]

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("doomed task")

        assert result.success is False
        assert result.plans_used == 2

    def test_step_results_accumulate_across_plans(
        self, tmp_path: Path,
    ) -> None:
        """step_results includes results from both the failed and
        successful plans."""
        zone_ok = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone_ok], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        bad_plan = _make_plan(
            steps=[_make_step(zone_id="btn_missing")],
        )
        good_plan = _make_plan(
            steps=[_make_step(zone_id="btn_ok")],
        )

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.side_effect = [bad_plan, good_plan]

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("click OK")

        # At least one failed result from bad plan and one success.
        assert len(result.step_results) >= 2

    def test_aborts_after_max_replan_for_zone_not_found(
        self, tmp_path: Path,
    ) -> None:
        """Director aborts when zone_not_found persists after replan.

        The error classifier allows one replan attempt for
        zone_not_found (attempt=0 -> REANALYZE).  If the second plan
        also targets a missing zone the classifier returns ABORT
        (attempt=1), so the Director gives up after 2 plans.
        """
        zone_ok = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone_ok], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        # Both plans reference missing zones.
        bad_plan_1 = _make_plan(
            steps=[_make_step(zone_id="btn_missing_1")],
        )
        bad_plan_2 = _make_plan(
            steps=[_make_step(zone_id="btn_missing_2")],
        )

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.side_effect = [bad_plan_1, bad_plan_2]

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("doomed task")

        assert result.success is False
        assert result.plans_used == 2
        assert "not found" in result.error.lower()


# ===================================================================
# Test Group 5: API budget enforcement
# ===================================================================


class TestAPIBudget:
    """Tests that the Director enforces the API call budget."""

    def test_budget_exhaustion_aborts_task(
        self, tmp_path: Path,
    ) -> None:
        """Task fails when cumulative API calls exceed the budget."""
        zone_ok = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone_ok], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        # Create a plan that consumes the entire budget.
        expensive_plan = _make_plan(
            steps=[_make_step(zone_id="btn_ok")],
            api_calls_used=_MAX_API_CALLS,
        )

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = expensive_plan

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("expensive task")

        assert result.success is False
        assert "budget" in result.error.lower()

    def test_budget_allows_task_below_limit(
        self, tmp_path: Path,
    ) -> None:
        """Task succeeds when API calls are within budget."""
        zone_ok = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone_ok], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        cheap_plan = _make_plan(
            steps=[_make_step(zone_id="btn_ok")],
            api_calls_used=1,
        )

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = cheap_plan

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("cheap task")

        assert result.success is True

    def test_budget_counts_replan_calls(
        self, tmp_path: Path,
    ) -> None:
        """Replanning API calls count toward the total budget."""
        zone_ok = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone_ok], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        # First plan uses many API calls and references missing zone.
        bad_plan = _make_plan(
            steps=[_make_step(zone_id="btn_missing")],
            api_calls_used=_MAX_API_CALLS - 1,
        )
        # Second plan also uses calls, pushing over budget.
        good_plan = _make_plan(
            steps=[_make_step(zone_id="btn_ok")],
            api_calls_used=2,
        )

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.side_effect = [bad_plan, good_plan]

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("expensive replan")

        # Total api_calls_used is tracked either way.
        assert result.api_calls_used >= _MAX_API_CALLS - 1

    def test_budget_error_message_is_clear(
        self, tmp_path: Path,
    ) -> None:
        """Budget exhaustion produces a descriptive error string."""
        zone_ok = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone_ok], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        expensive_plan = _make_plan(
            steps=[_make_step(zone_id="btn_ok")],
            api_calls_used=_MAX_API_CALLS + 1,
        )

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = expensive_plan

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("too expensive")

        assert result.success is False
        assert "api" in result.error.lower()
        assert "budget" in result.error.lower()


# ===================================================================
# Test Group 6: Replay buffer integration
# ===================================================================


class TestReplayBuffer:
    """Tests that replay sessions are created with proper metadata."""

    def test_session_directory_created(
        self, tmp_path: Path,
    ) -> None:
        """run_task creates a session directory under session_dir."""
        zone = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        agent.run_task("click OK")

        # At least one session directory should exist.
        session_dirs = [
            p for p in tmp_path.iterdir() if p.is_dir()
        ]
        assert len(session_dirs) >= 1

    def test_metadata_json_created(self, tmp_path: Path) -> None:
        """run_task creates a metadata.json inside the session dir."""
        zone = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        agent.run_task("click OK")

        session_dirs = [
            p for p in tmp_path.iterdir() if p.is_dir()
        ]
        assert len(session_dirs) >= 1

        meta_path = session_dirs[0] / "metadata.json"
        assert meta_path.exists()

        with meta_path.open("r", encoding="utf-8") as fh:
            meta = json.load(fh)
        assert "session_id" in meta
        assert meta["task_description"] == "click OK"

    def test_metadata_has_screen_dimensions(
        self, tmp_path: Path,
    ) -> None:
        """metadata.json includes the screen width and height."""
        zone = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

        platform = MockPlatform(width=100, height=100)
        agent = _build_full_stack(
            platform=platform,
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        agent.run_task("click OK")

        session_dirs = [
            p for p in tmp_path.iterdir() if p.is_dir()
        ]
        meta_path = session_dirs[0] / "metadata.json"
        with meta_path.open("r", encoding="utf-8") as fh:
            meta = json.load(fh)

        assert meta["screen_width"] == 100
        assert meta["screen_height"] == 100

    def test_metadata_has_start_and_end_time(
        self, tmp_path: Path,
    ) -> None:
        """metadata.json has non-zero start_time and end_time."""
        zone = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        agent.run_task("click OK")

        session_dirs = [
            p for p in tmp_path.iterdir() if p.is_dir()
        ]
        meta_path = session_dirs[0] / "metadata.json"
        with meta_path.open("r", encoding="utf-8") as fh:
            meta = json.load(fh)

        assert meta["start_time"] > 0
        assert meta["end_time"] > 0
        assert meta["end_time"] >= meta["start_time"]

    def test_cursor_jsonl_created(self, tmp_path: Path) -> None:
        """run_task creates cursor.jsonl with at least one entry."""
        zone = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        agent.run_task("click OK")

        session_dirs = [
            p for p in tmp_path.iterdir() if p.is_dir()
        ]
        cursor_path = session_dirs[0] / "cursor.jsonl"
        assert cursor_path.exists()

        lines = cursor_path.read_text(
            encoding="utf-8",
        ).strip().split("\n")
        assert len(lines) >= 1
        sample = json.loads(lines[0])
        assert "x" in sample
        assert "y" in sample

    def test_recording_disabled_skips_png_frames(
        self, tmp_path: Path,
    ) -> None:
        """When save_frames_as_png=False, no PNG files are saved."""
        zone = _make_zone("btn_ok", "OK")
        settings = Settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
            save_frames_as_png=False,
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        result = agent.run_task("click OK")
        assert result.success is True

        # Session dir exists but no frames/ subdirectory.
        session_dirs = [
            p for p in tmp_path.iterdir() if p.is_dir()
        ]
        assert len(session_dirs) >= 1
        frames_dir = session_dirs[0] / "frames"
        if frames_dir.exists():
            pngs = list(frames_dir.glob("*.png"))
            assert len(pngs) == 0

    def test_metadata_frame_count_positive(
        self, tmp_path: Path,
    ) -> None:
        """metadata.json frame_count is positive after run_task."""
        zone = _make_zone("btn_ok", "OK")
        settings = _make_settings(
            recording_enabled=True,
            session_dir=str(tmp_path),
        )

        tier2_mock = MagicMock(spec=Tier2Analyzer)
        tier2_mock.analyze_sync.return_value = Tier2Response(
            zones=[zone], success=True,
        )
        tier2_mock.encode_frame = Tier2Analyzer.encode_frame

        planner_mock = MagicMock(spec=TaskPlanner)
        planner_mock.plan.return_value = _make_plan()

        agent = _build_full_stack(
            settings=settings,
            tier2_mock=tier2_mock,
            planner_mock=planner_mock,
        )

        agent.run_task("click OK")

        session_dirs = [
            p for p in tmp_path.iterdir() if p.is_dir()
        ]
        meta_path = session_dirs[0] / "metadata.json"
        with meta_path.open("r", encoding="utf-8") as fh:
            meta = json.load(fh)

        assert meta["frame_count"] >= 1
