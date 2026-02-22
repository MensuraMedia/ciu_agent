# CIU Agent — Build Phases

## Phase Overview

| Phase | Name | Status | Primary Team | Est. Tasks |
|-------|------|--------|--------------|------------|
| 1 | Foundation | Not Started | Foundation | 12-15 |
| 2 | Canvas | Not Started | Canvas | 10-12 |
| 3 | Brush | Not Started | Brush | 8-10 |
| 4 | Director | Not Started | Director | 8-10 |
| 5 | Integration | Not Started | Integration | 10-15 |

## Phase 1: Foundation

**Goal:** Continuous screen capture and cursor tracking working cross-platform.

### Deliverables

1. `ciu_agent/platform/interface.py` — Abstract base class defining PlatformInterface with all method signatures, type hints, and docstrings.
2. `ciu_agent/platform/windows.py` — Windows implementation of PlatformInterface.
3. `ciu_agent/platform/linux.py` — Linux implementation of PlatformInterface.
4. `ciu_agent/platform/macos.py` — macOS implementation of PlatformInterface.
5. `ciu_agent/core/capture_engine.py` — Capture engine with frame ring buffer, cursor position stream, and frame timestamping.
6. Frame differencing (Tier 0) integrated into the capture engine.
7. `ciu_agent/core/replay_buffer.py` — Session recording to disk (frames, cursor positions, metadata).
8. `ciu_agent/models/zone.py` — Zone data model (dataclass).
9. `ciu_agent/models/events.py` — Spatial event definitions.
10. `ciu_agent/models/actions.py` — Action definitions.
11. `ciu_agent/config/settings.py` — Configuration defaults (frame rate, buffer size, thresholds).
12. `requirements.txt` — All dependencies pinned.
13. `tests/` — Unit tests for capture engine and platform layer.

### Acceptance Criteria

- Screen capture runs at 15+ fps on the target hardware (Intel UHD, Windows)
- Cursor position stream is synchronized with frame timestamps
- Frame differencing correctly detects when the screen changes vs when it's static
- Session recording produces a playable .mp4 and a cursor.jsonl file
- At least one platform implementation passes all tests
- Zone, Event, and Action data models are defined and importable

### Dependencies

None. This is the starting phase.

## Phase 2: Canvas

**Goal:** Build and maintain a persistent zone map of the screen.

### Deliverables

1. `ciu_agent/core/canvas_mapper.py` — Canvas Mapper with zone registry and tiered analysis.
2. Tier 2 full analysis prompt and response parser for Claude API.
3. Tier 1 local region analysis (OCR, template matching) for common UI changes.
4. Tier 0 integration — frame differencer triggers Tier 1/2 as appropriate.
5. Zone registry data structure with CRUD operations.
6. State change detection heuristics (classify diff results into tiers).
7. Tests for canvas mapper, zone registry, and tier escalation logic.

### Acceptance Criteria

- Can map a desktop with multiple windows and produce a zone inventory
- Zone registry persists correctly when cursor moves (no false rebuilds)
- Tier 0 correctly ignores cursor-only movement
- Tier 1 correctly updates zones when a tooltip or hover effect appears
- Tier 2 correctly rebuilds the zone map when a new application window opens
- API call count is minimized (Tier 2 triggers only on major state changes)

### Dependencies

- Phase 1 complete (capture engine provides frame stream and cursor position)

## Phase 3: Brush

**Goal:** Real-time cursor-to-zone tracking with spatial events and action execution.

### Deliverables

1. `ciu_agent/core/brush_controller.py` — Brush Controller with zone tracking, event emission, motion planning, and action execution.
2. Spatial event stream (zone_enter, zone_exit, zone_hover, zone_click, zone_type, brush_lost).
3. Motion trajectory planner (direct, safe, exploratory paths).
4. Action execution pipeline (click, type, scroll) with zone verification.
5. Brush-lost detection and reporting.
6. Tests for zone tracking, event emission, motion planning.

### Acceptance Criteria

- Cursor position is continuously mapped to the correct zone from the registry
- Spatial events fire at the correct times (enter when crossing boundary, exit when leaving)
- Motion planner generates valid trajectories that reach target zones
- Action execution verifies the cursor is in the target zone before acting
- Brush-lost condition is detected when cursor position doesn't match expected trajectory

### Dependencies

- Phase 1 complete (platform layer for input injection)
- Phase 2 complete (canvas mapper provides zone registry)

## Phase 4: Director

**Goal:** Accept natural language tasks and execute them through zone interactions.

### Deliverables

1. `ciu_agent/core/director.py` — Director with task decomposition, step execution, and error handling.
2. Task decomposition via Claude API (natural language to zone interaction sequence).
3. Step-by-step execution loop through Brush Controller.
4. Error detection and classification (wrong zone, timeout, zone not found, etc.).
5. Re-planning logic for common error types.
6. Task completion verification.
7. Tests with mocked API responses and simulated canvas states.

### Acceptance Criteria

- Can decompose a simple task ("open Notepad and type hello world") into correct zone steps
- Executes steps in order through the Brush Controller
- Detects when an action doesn't produce the expected canvas change
- Re-plans when a step fails (e.g., zone not found triggers re-analysis)
- Reports task completion or failure with explanation
- API calls for planning are under 10 per typical task

### Dependencies

- Phase 2 complete (canvas mapper for zone data)
- Phase 3 complete (brush controller for action execution)

## Phase 5: Integration and Hardening

**Goal:** Full system operating reliably end-to-end.

### Deliverables

1. Main entry point (`ciu_agent/main.py`) wiring all components together.
2. End-to-end integration tests.
3. Cross-platform validation (at minimum Windows + one other).
4. Performance optimization (frame rate, API latency, memory usage).
5. Replay viewer for debugging sessions.
6. Error recovery for all classified error types.
7. README with setup, usage, and examples.
8. API documentation for all public interfaces.
9. CHANGELOG.md

### Acceptance Criteria

- Agent can execute a 10+ step task end-to-end on Windows
- Error recovery handles at least 3 classified error types without human intervention
- Frame capture maintains 15+ fps during operation
- API calls stay under budget for typical usage patterns
- Replay viewer can play back a recorded session with cursor overlay
- All tests pass
- Documentation is complete and accurate

### Dependencies

- Phases 1-4 complete
