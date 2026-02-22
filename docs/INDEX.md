# CIU Agent — Complete File Index

> Complete Interface Usage Agent — a visual GUI agent that treats the
> screen as a canvas and the cursor as a brush.

Last updated: 2026-02-22 | 900 tests | 5 phases complete

---

## Architecture Overview

The CIU Agent is built in five layers, each implemented as a separate phase:

```
Phase 1: Capture Engine + Platform Layer (foundation)
Phase 2: Canvas Mapper + Zone Registry (perception)
Phase 3: Brush Controller + Spatial Events (motor control)
Phase 4: Director + Task Planner (cognition)
Phase 5: Integration + Hardening (full agent)
```

Three analysis tiers process screen data:

| Tier | Scope | Engine | Latency |
|------|-------|--------|---------|
| Tier 0 | Frame diff | NumPy pixel comparison | <1 ms |
| Tier 1 | Region analysis | OpenCV contour/OCR | 5-50 ms |
| Tier 2 | Full analysis | Claude API vision | 5-30 s |

Two execution modes:

| Mode | Description | Zone ID |
|------|-------------|---------|
| Visual | Cursor navigates to detected zone, physically clicks | Zone ID from registry |
| Command | Keyboard shortcut sent directly via platform | `__global__` |

---

## Source Files

### Entry Point

| File | Lines | Purpose |
|------|-------|---------|
| `ciu_agent/main.py` | 473 | **Top-level agent and CLI.** Contains `CIUAgent` dataclass (holds all 17 component references), `build_agent()` factory (wires components in dependency order), `startup()` (initial screen capture + Tier 2 analysis), `run_task()` (full task execution with replay recording), and `main()` CLI with `--task`, `--api-key`, `--verbose` arguments. Also provides `_recapture()` callback for Director to re-analyse the screen between steps. |

### Configuration

| File | Lines | Purpose |
|------|-------|---------|
| `ciu_agent/config/__init__.py` | 0 | Package marker. |
| `ciu_agent/config/settings.py` | 148 | **Immutable Settings dataclass.** All tunable parameters for every component: `target_fps`, `diff_threshold_percent`, `tier2_threshold_percent`, `stability_wait_ms`, `min_zone_confidence`, `zone_expiry_seconds`, `hover_threshold_ms`, `motion_speed_pixels_per_sec`, `step_delay_seconds` (2.0s default — delay between Director steps), `api_timeout_vision_seconds` (30s), `api_timeout_text_seconds` (30s), `api_max_retries` (3), `api_backoff_base_seconds` (2.0), `recording_enabled`, `session_dir`, `platform_name`. Provides `from_dict()` and `to_dict()` for serialisation. |

### Core Components

| File | Lines | Purpose |
|------|-------|---------|
| `ciu_agent/core/capture_engine.py` | 294 | **Phase 1 — Screen capture with ring buffer.** `CaptureEngine` captures frames via `PlatformInterface.capture_frame()`, wraps them in `CaptureFrame` (image + cursor position + timestamp), and stores them in a ring buffer. Provides `capture_to_buffer()`, `capture_single()`, `get_latest_frame()`, `get_buffer_frames()`. |
| `ciu_agent/core/state_classifier.py` | 487 | **Phase 2 — Heuristic frame-diff classifier.** Compares consecutive frames using pixel-level differencing (Tier 0). Classifies changes as `IDLE`, `CURSOR_ONLY`, `MINOR_UPDATE`, `CONTENT_CHANGE`, or `PAGE_NAVIGATION` based on `diff_threshold_percent` and `tier2_threshold_percent`. Implements stability-wait logic (`stability_wait_ms`) to let animations settle. |
| `ciu_agent/core/tier1_analyzer.py` | 773 | **Phase 2 — Local region analyser.** Uses OpenCV to detect UI elements within changed screen regions: contour detection, edge-based region extraction, basic OCR-like text detection, and button/input field classification. Returns zone updates without API calls. |
| `ciu_agent/core/tier2_analyzer.py` | 639 | **Phase 2 — Claude API vision analyser.** Sends JPEG-encoded screenshots to the Claude Messages API (`claude-sonnet-4-20250514`) with a structured prompt requesting zone detection. Returns `Tier2Response` with a list of `Zone` objects including bounding boxes, types, and states. Handles retry with exponential backoff. |
| `ciu_agent/core/zone_registry.py` | 312 | **Phase 2 — Thread-safe zone storage.** Central repository of detected UI zones. Supports `register()`, `register_many()`, `replace_all()`, `remove()`, `get()`, `get_all()`, `contains()`, `find_by_label()`, `find_by_type()`, `get_nearest()`, `expire_stale()`. Thread-safe via `threading.Lock`. |
| `ciu_agent/core/canvas_mapper.py` | 493 | **Phase 2 — Analysis tier orchestrator.** Routes frames through the three analysis tiers based on change classification. `process_frame()` runs Tier 0 diff, classifies the change, applies Tier 1 for minor updates, and delegates to Tier 2 for major changes. Updates the zone registry automatically. |
| `ciu_agent/core/zone_tracker.py` | 320 | **Phase 3 — Cursor-to-zone spatial events.** Tracks cursor position against registered zones, emitting `ZONE_ENTER`, `ZONE_EXIT`, `ZONE_HOVER` events. Maintains event history with configurable depth (default 1000). |
| `ciu_agent/core/motion_planner.py` | 550 | **Phase 3 — Cursor trajectory generation.** Generates smooth mouse movement paths from current position to target zone centers. Supports linear, bezier, and natural motion curves with configurable speed (`motion_speed_pixels_per_sec`). |
| `ciu_agent/core/action_executor.py` | 455 | **Phase 3 — Zone-verified input execution.** Performs input actions (click, double-click, type, key_press, scroll, move, drag) via the platform layer AFTER verifying the cursor is inside the target zone. Dispatch table maps `ActionType` to handler methods. |
| `ciu_agent/core/brush_controller.py` | 512 | **Phase 3 — High-level cursor/action controller.** The "brush" in the canvas metaphor. Combines `ZoneTracker` + `MotionPlanner` + `ActionExecutor` into a single `execute_action()` API: navigate cursor to zone, verify arrival, perform action. Returns `BrushActionResult` with navigation and action details. |
| `ciu_agent/core/task_planner.py` | 546 | **Phase 4 — Claude API task decomposer.** Sends task description + zone list to Claude API to produce step-by-step plans. System prompt encodes the 8-step methodology (examine screen, identify OS, locate launcher, access launcher, find app, wait, operate, complete) and dual execution modes (Visual + Command). Returns `TaskPlan` with ordered `TaskStep` objects. Includes `platform_name` in prompts for OS-specific shortcuts. |
| `ciu_agent/core/step_executor.py` | 395 | **Phase 4 — TaskStep-to-BrushController bridge.** Maps planner action-type strings to `ActionType` enums, verifies zones exist, builds `Action` objects, delegates to `BrushController.execute_action()`. Supports `__global__` zone for OS-level actions (key_press, type_text, click) executed directly through the platform without zone navigation. Returns `StepResult` with error categorisation (`zone_not_found`, `action_failed`, `brush_lost`). |
| `ciu_agent/core/error_classifier.py` | 419 | **Phase 4 — Failure classification and recovery.** Classifies step failures into recovery actions: `RETRY` (transient), `REPLAN` (zone changed), `REANALYZE` (screen changed), `SKIP` (non-critical), `ABORT` (fatal). Supports escalation when retries are exhausted. |
| `ciu_agent/core/director.py` | 545 | **Phase 4 — Top-level task orchestrator.** Accepts natural-language tasks, decomposes via `TaskPlanner`, executes via `StepExecutor`, handles errors via `ErrorClassifier`. Re-captures screen between steps with major UI transitions (via `recapture_fn` callback). Enforces API budget (`_MAX_API_CALLS=20`), replan limit (`_MAX_REPLANS=3`), step retries (`_MAX_STEP_RETRIES=3`). Configurable `step_delay_seconds` between actions. |
| `ciu_agent/core/replay_buffer.py` | 414 | **Phase 5 — Session recording.** Records frames, cursor positions, spatial events, and director decisions to disk. `start_session()` / `stop_session()` lifecycle. Writes `metadata.json`, `cursor.jsonl`, and optional PNG frames. |
| `ciu_agent/replay_viewer.py` | 854 | **Phase 5 — Replay playback CLI.** `SessionLoader` reads recorded sessions, `ReplayViewer` plays them back with OpenCV display showing cursor overlay and zone boundaries. Supports step-through and continuous modes. |

### Data Models

| File | Lines | Purpose |
|------|-------|---------|
| `ciu_agent/models/__init__.py` | 0 | Package marker. |
| `ciu_agent/models/zone.py` | 200 | **Zone data model.** `Zone` dataclass with `id`, `label`, `type` (ZoneType enum: BUTTON, TEXT_FIELD, MENU, etc.), `state` (ZoneState: ENABLED, DISABLED, etc.), `bounds` (BoundingBox with `contains_point()`, `center()`, `iou()`), `confidence`, `timestamp`. |
| `ciu_agent/models/actions.py` | 121 | **Action data model.** `Action` dataclass with `type` (ActionType enum: CLICK, DOUBLE_CLICK, TYPE_TEXT, KEY_PRESS, SCROLL, MOVE, DRAG), `target_zone_id`, `parameters` dict, `status` (ActionStatus: PENDING, IN_PROGRESS, COMPLETED, FAILED), `result`, `timestamp`. |
| `ciu_agent/models/events.py` | ~80 | **Spatial event model.** `SpatialEvent` dataclass with `type` (SpatialEventType: ZONE_ENTER, ZONE_EXIT, ZONE_HOVER, ZONE_CLICK, ZONE_TYPE), `zone_id`, `timestamp`, `position`, `data`. |
| `ciu_agent/models/task.py` | ~100 | **Task planning model.** `TaskStep` dataclass with `step_number`, `zone_id`, `zone_label`, `action_type`, `parameters`, `expected_change`, `description`. `TaskPlan` dataclass with `task_description`, `steps`, `raw_response`, `success`, `error`, `api_calls_used`, `latency_ms`. |

### Platform Layer

| File | Lines | Purpose |
|------|-------|---------|
| `ciu_agent/platform/__init__.py` | 0 | Package marker. |
| `ciu_agent/platform/interface.py` | 220 | **Abstract platform interface.** `PlatformInterface` ABC defining the contract: `capture_frame()`, `get_cursor_pos()`, `move_cursor()`, `click()`, `double_click()`, `scroll()`, `type_text()`, `key_press()`, `get_screen_size()`, `get_active_window()`, `list_windows()`, `get_platform_name()`, `close()`. `WindowInfo` dataclass. `create_platform()` factory with auto-detection. |
| `ciu_agent/platform/windows.py` | 457 | **Windows implementation.** Uses `mss` for screen capture (Desktop Duplication API), `ctypes` + Win32 API for cursor/screen/window queries, `pynput` for input injection. DPI-awareness via `SetProcessDpiAwareness`. Key resolution via `_KEY_MAP` (40+ keys) and `_resolve_key()`. Supports modifier combos like `ctrl+shift+s`. |
| `ciu_agent/platform/linux.py` | 187 | **Linux stub.** Placeholder with `NotImplementedError` for all methods. Ready for X11/Wayland implementation. |
| `ciu_agent/platform/macos.py` | 187 | **macOS stub.** Placeholder with `NotImplementedError` for all methods. Ready for Quartz implementation. |

---

## Test Files

| File | Lines | Tests | Covers |
|------|-------|-------|--------|
| `tests/test_capture_engine.py` | 815 | ~40 | CaptureEngine ring buffer, frame capture, timing |
| `tests/test_state_classifier.py` | 659 | ~30 | StateClassifier change types, stability wait |
| `tests/test_tier1_analyzer.py` | 576 | ~25 | Tier1Analyzer contour/region detection |
| `tests/test_tier2_analyzer.py` | 727 | ~35 | Tier2Analyzer API call, retry, zone parsing |
| `tests/test_zone_registry.py` | 729 | ~40 | ZoneRegistry CRUD, expiry, thread safety |
| `tests/test_canvas_mapper.py` | 1133 | ~50 | CanvasMapper tier routing, zone updates |
| `tests/test_zone_tracker.py` | 1083 | ~50 | ZoneTracker spatial events, hover, history |
| `tests/test_motion_planner.py` | 753 | ~35 | MotionPlanner trajectory generation |
| `tests/test_action_executor.py` | 876 | ~40 | ActionExecutor zone verification, dispatch |
| `tests/test_brush_controller.py` | 817 | ~35 | BrushController navigate + action pipeline |
| `tests/test_task_planner.py` | 799 | ~40 | TaskPlanner prompt building, response parsing |
| `tests/test_step_executor.py` | 802 | ~35 | StepExecutor action mapping, __global__ zone |
| `tests/test_error_classifier.py` | 405 | ~20 | ErrorClassifier recovery actions |
| `tests/test_director.py` | 889 | ~30 | Director task execution, replan, budget |
| `tests/test_integration.py` | 1498 | ~42 | End-to-end pipeline, startup, replay |
| `tests/test_models.py` | 611 | ~30 | Zone, Action, Event, Task dataclasses |
| `tests/test_settings.py` | 256 | ~15 | Settings defaults, from_dict, to_dict |
| `tests/test_platform.py` | 237 | ~10 | Platform factory, WindowInfo |
| `tests/test_replay_buffer.py` | 524 | ~25 | ReplayBuffer session lifecycle |

**Total: 900 tests, ~25,800 lines of code + tests**

---

## Documentation Files

| File | Purpose |
|------|---------|
| `docs/architecture.md` | Full system design — component diagram, data flow, tier pipeline |
| `docs/phases.md` | Detailed spec for each of the 5 build phases |
| `docs/taskboard.json` | Phase 5 task tracking (6 tasks) |
| `docs/INDEX.md` | **This file** — complete file index with purpose and reasoning |
| `docs/agents.md` | Claude Code agent definitions used during development |
| `docs/conductor.md` | Conductor agent orchestration spec |
| `docs/features.md` | Feature backlog and priorities |
| `docs/permissions.md` | Permission model for agent actions |
| `docs/skills.md` | Claude Code skill definitions |
| `docs/teams.md` | Multi-agent team definitions |
| `docs/token_*.md` | Token budget tracking and cost analysis |
| `CHANGELOG.md` | Version history in Keep a Changelog format |
| `README.md` | Installation, usage, API overview, architecture summary |
| `CLAUDE.md` | Claude Code project instructions and conventions |

---

## Key Design Decisions

### Why "Canvas + Brush" Metaphor?
The screen is treated as a canvas and the cursor as a brush. This mental model cleanly separates **perception** (canvas mapper detects zones) from **motor control** (brush moves cursor to zones and acts). The Director is the "artist" that decides what to paint.

### Why Three Analysis Tiers?
Cost optimisation. Tier 0 (pixel diff) runs every frame for free. Tier 1 (OpenCV) runs on changed regions locally. Tier 2 (Claude API) only fires on major screen changes. This keeps API costs under control while maintaining situational awareness.

### Why Dual Execution Modes?
"Complete Interface Usage" means the agent must handle BOTH scenarios:
- **Visual mode**: When UI zones are detected (buttons, menus, text fields), the agent physically moves the cursor to them — providing visual feedback and working like a human user.
- **Command mode**: When no zone exists for an action (OS-level shortcuts like Win+R, Ctrl+S), the agent uses keyboard shortcuts via the `__global__` zone.

### Why Screen Re-capture Between Steps?
After actions that change the UI (launching an app, opening a dialog), the agent must re-analyse the screen to detect new zones. The Director calls `recapture_fn` between steps when `expected_change` suggests a major transition, then subsequent steps can use newly detected zones in Visual mode.

### Why Dependency Injection Everywhere?
Every component receives its dependencies through the constructor. No global state, no singletons, no hidden coupling. This makes testing trivial (inject mocks), components replaceable, and the dependency graph explicit.

### Why Platform Abstraction?
All OS-specific code lives in `ciu_agent/platform/`. Core logic never imports Windows/Linux/macOS APIs. This enables cross-platform support and makes the core testable with `MockPlatform`.

---

## Dependency Graph

```
main.py
├── CaptureEngine ← PlatformInterface
├── ZoneRegistry
├── StateClassifier
├── Tier1Analyzer
├── Tier2Analyzer ← Claude API
├── CanvasMapper ← Registry + Classifier + Tier1 + Tier2
├── ZoneTracker ← Registry
├── MotionPlanner ← Registry
├── ActionExecutor ← PlatformInterface + Registry
├── BrushController ← Platform + Registry + Tracker + Planner + Executor
├── TaskPlanner ← Claude API
├── StepExecutor ← BrushController + Registry + PlatformInterface
├── ErrorClassifier
├── Director ← TaskPlanner + StepExecutor + ErrorClassifier + Registry + CanvasMapper
└── ReplayBuffer
```
