# CIU Agent — Agents and Sub-Agents

## Agent Architecture

The CIU Agent build uses a conductor pattern with specialized agents. Each agent owns a domain. Sub-agents handle focused tasks within that domain. The conductor orchestrates across domains.

## Agent Roster

### Agent: Architect

**Role:** System design and cross-component decisions.
**Owns:** Architecture docs, component interfaces, data model definitions.
**Model tier:** Opus (high reasoning required)

Responsibilities:

- Define and maintain component interfaces
- Resolve cross-component design conflicts
- Review structural changes before merge
- Approve new data models and event definitions

Sub-agents:

- `architect:interface-reviewer` — Validates that component boundaries are respected. Checks that `core/` has no platform-specific code. Checks that models are used consistently.
- `architect:dependency-auditor` — Reviews imports and dependencies. Flags circular dependencies. Verifies no unnecessary external packages.

### Agent: Platform Engineer

**Role:** Cross-platform abstraction layer.
**Owns:** `ciu_agent/platform/` directory.
**Model tier:** Sonnet (implementation-focused)

Responsibilities:

- Implement platform-specific capture, input, and cursor functions
- Maintain the abstract `PlatformInterface`
- Write platform-specific tests
- Handle DPI/scaling normalization

Sub-agents:

- `platform:linux-impl` — Linux-specific implementation using Xlib, xdotool, PipeWire.
- `platform:windows-impl` — Windows-specific implementation using ctypes, DXGI, SendInput.
- `platform:macos-impl` — macOS-specific implementation using Quartz, CGEvent.
- `platform:test-runner` — Runs platform-specific tests in isolated environments.

### Agent: Capture Specialist

**Role:** Screen recording and frame pipeline.
**Owns:** `ciu_agent/core/capture_engine.py`, frame buffer, diff engine.
**Model tier:** Sonnet

Responsibilities:

- Implement continuous screen capture at target frame rate
- Build the frame ring buffer
- Implement Tier 0 frame differencing
- Synchronize frame timestamps with cursor position stream
- Manage session recording to disk

Sub-agents:

- `capture:frame-differ` — Implements and optimizes the frame differencing algorithm. Tunes thresholds for change detection.
- `capture:recorder` — Handles ffmpeg integration for session video recording.

### Agent: Canvas Specialist

**Role:** Zone segmentation and spatial map management.
**Owns:** `ciu_agent/core/canvas_mapper.py`, zone registry, analysis tiers.
**Model tier:** Opus (requires vision-language reasoning for Tier 2 prompts)

Responsibilities:

- Design and maintain the Zone data model
- Implement Tier 1 local region analysis
- Design Tier 2 API prompts for full canvas analysis
- Maintain the Zone Registry with incremental updates
- Implement state change detection heuristics

Sub-agents:

- `canvas:zone-detector` — Runs local segmentation (OCR, template matching, edge detection) for Tier 1 updates.
- `canvas:api-analyst` — Constructs and sends Tier 2 analysis requests to Claude API. Parses structured zone data from responses.
- `canvas:registry-manager` — Manages zone lifecycle: creation, update, expiry, conflict resolution.

### Agent: Brush Specialist

**Role:** Cursor tracking and action execution.
**Owns:** `ciu_agent/core/brush_controller.py`, spatial events, motion planning.
**Model tier:** Sonnet

Responsibilities:

- Implement continuous cursor-to-zone mapping
- Emit spatial events (enter, exit, hover)
- Plan and execute cursor motion trajectories
- Execute zone actions (click, type, scroll)
- Detect brush-lost conditions

Sub-agents:

- `brush:motion-planner` — Calculates trajectory paths (direct, safe, exploratory). Handles collision avoidance with non-target zones.
- `brush:event-emitter` — Manages the spatial event stream. Debounces rapid zone transitions. Handles edge cases (cursor on zone boundary).

### Agent: Director Specialist

**Role:** High-level task planning and execution management.
**Owns:** `ciu_agent/core/director.py`, task decomposition, error recovery.
**Model tier:** Opus

Responsibilities:

- Accept natural language task descriptions
- Decompose tasks into zone interaction sequences
- Manage step-by-step execution via Brush Controller
- Handle errors and trigger re-planning
- Verify task completion

Sub-agents:

- `director:task-planner` — Converts natural language tasks into structured step sequences. Uses Claude API for complex decomposition.
- `director:error-handler` — Detects when execution deviates from plan. Classifies error types. Decides between retry, undo, or re-plan.
- `director:verifier` — After task completion, validates that the expected outcome was achieved by checking canvas state.

### Agent: Token Warden

**Role:** Token budget enforcement and cost monitoring.
**Owns:** `docs/token_log.md`, `docs/token_violations.md`, `docs/token_reviews.md`.
**Model tier:** Sonnet (threshold-based decisions only, thinking budget: 4000)

Responsibilities:

- Audit MCP configuration and env vars at session startup
- Track per-agent token usage against budget ceilings
- Enforce compaction when agents hit 70% of their budget
- Monitor task-to-tool routing compliance (per `docs/token_ops.md`)
- Log violations and escalate repeat offenders to Conductor
- Produce session-end token reports and weekly reviews

Sub-agents: None. The Token Warden operates alone to minimize its own token footprint.

See `docs/token_warden_agent.md` for full specification.

### Agent: Test Engineer

**Role:** Testing and validation across all components.
**Owns:** `tests/` directory.
**Model tier:** Sonnet

Responsibilities:

- Write unit tests for all components
- Write integration tests for component interactions
- Create mock platform implementations for testing
- Validate cross-platform behavior

Sub-agents:

- `test:unit-writer` — Generates unit tests for new functions and classes.
- `test:integration-writer` — Builds integration tests that exercise multiple components together.
- `test:mock-builder` — Creates mock objects for platform interfaces, API responses, and screen captures.

### Agent: Documentation

**Role:** Keep all docs current and accurate.
**Owns:** `docs/` directory, README, inline docstrings.
**Model tier:** Sonnet

Responsibilities:

- Update architecture docs when design changes
- Maintain README with current project state
- Ensure all public APIs have docstrings
- Keep build phase tracking current

Sub-agents:

- `docs:api-documenter` — Scans public interfaces and generates/updates docstrings.
- `docs:changelog-writer` — Maintains CHANGELOG.md with entries for each significant change.

## Agent Communication

Agents communicate through:

1. **Shared task board** — JSON file tracking current tasks, owners, status, and dependencies.
2. **Inter-agent messages** — When an agent's work affects another's domain, it sends a notification via the mailbox system.
3. **Review requests** — Before merging changes that cross component boundaries, the Architect agent reviews.

## Spawning Rules

- Only the Conductor (see `docs/conductor.md`) spawns agents
- Agents spawn their own sub-agents as needed
- Sub-agents report back to their parent agent only
- Maximum concurrent agents: 5 (to manage context and API costs)
- Each agent works in its own context window
