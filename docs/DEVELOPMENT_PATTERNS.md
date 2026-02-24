# Development Patterns for Autonomous Agents

> Universal code patterns extracted from the CIU Agent that apply to
> any autonomous agent system — GUI automation, web scraping, RPA,
> game AI, DevOps, or any LLM-driven process.

---

## Table of Contents

1. [The Component Graph Pattern](#1-the-component-graph-pattern)
2. [The Settings Dataclass Pattern](#2-the-settings-dataclass-pattern)
3. [The Abstract Platform Pattern](#3-the-abstract-platform-pattern)
4. [The Request-Response Model Pattern](#4-the-request-response-model-pattern)
5. [The Step-Based Execution Pattern](#5-the-step-based-execution-pattern)
6. [The Error Classification Pattern](#6-the-error-classification-pattern)
7. [The Zone-Based Interaction Model](#7-the-zone-based-interaction-model)
8. [The Event-Driven Observation Pattern](#8-the-event-driven-observation-pattern)
9. [The Replay Buffer Pattern](#9-the-replay-buffer-pattern)
10. [The Mock-Everything Testing Pattern](#10-the-mock-everything-testing-pattern)
11. [The Structured Logging Pattern](#11-the-structured-logging-pattern)
12. [The Prompt Engineering Pattern](#12-the-prompt-engineering-pattern)
13. [The Factory Function Pattern](#13-the-factory-function-pattern)
14. [The Idempotent Shutdown Pattern](#14-the-idempotent-shutdown-pattern)

---

## 1. The Component Graph Pattern

### Principle

Agents are built from a **directed acyclic graph** of collaborating
components. Each component has a single responsibility and communicates
through well-defined interfaces.

### CIU Agent Component Graph

```
                        ┌──────────┐
                        │ Director │  (orchestrator)
                        └────┬─────┘
                ┌────────────┼────────────┐
                ▼            ▼            ▼
         ┌────────────┐ ┌──────────┐ ┌───────────────┐
         │TaskPlanner │ │StepExec  │ │ErrorClassifier│
         └────────────┘ └────┬─────┘ └───────────────┘
                             │
                    ┌────────┼────────┐
                    ▼        ▼        ▼
              ┌──────────┐ ┌──────┐ ┌──────────┐
              │BrushCtrl │ │Zone  │ │Platform  │
              └────┬─────┘ │Reg.  │ │Interface │
              ┌────┼────┐  └──────┘ └──────────┘
              ▼    ▼    ▼
         ┌──────┐┌────┐┌──────┐
         │Motion││Zone││Action│
         │Plan. ││Trk ││Exec  │
         └──────┘└────┘└──────┘
```

### The Universal Decomposition

Any agent can be decomposed into:

```
OBSERVE → UNDERSTAND → DECIDE → ACT → VERIFY
```

| Phase | CIU Component | Universal Role |
|-------|---------------|----------------|
| Observe | CaptureEngine | Read environment state |
| Understand | CanvasMapper + Tier1/2 | Parse and classify observations |
| Decide | Director + TaskPlanner | Choose next action |
| Act | BrushController + StepExecutor | Execute the action |
| Verify | ZoneTracker + Recapture | Confirm outcome |

### Anti-Pattern: The God Agent

```python
# WRONG — one class does everything
class Agent:
    def do_task(self, task):
        image = self.capture_screen()
        zones = self.call_api(image)
        plan = self.call_api_again(task, zones)
        for step in plan:
            self.move_mouse(step.x, step.y)
            self.click()
```

This is untestable, unreusable, and impossible to debug. Each concern
should be a separate component.

---

## 2. The Settings Dataclass Pattern

### Pattern

All configuration lives in a **single, frozen, immutable dataclass**
with sensible defaults:

```python
@dataclass(frozen=True)
class Settings:
    """Immutable configuration for the entire system."""

    # Capture
    target_fps: int = 15
    max_fps: int = 30

    # API
    api_timeout_vision_seconds: float = 60.0
    api_timeout_text_seconds: float = 30.0
    api_max_retries: int = 3
    api_backoff_base_seconds: float = 2.0

    # Director
    step_delay_seconds: float = 2.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        """Create from dict. Unknown keys silently ignored."""
        known_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known_names}
        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

### Why Frozen

| Property | Benefit |
|----------|---------|
| Immutable | Cannot be accidentally modified during execution |
| Thread-safe | Safe to share across threads/agents |
| Hashable | Can be used as dict key or set member |
| Predictable | Configuration is fixed from construction to shutdown |

### Why from_dict Ignores Unknown Keys

Forward compatibility — new config files work with older agent versions.

### Universal Application

Every agent system needs configuration. A frozen dataclass is the gold
standard because it combines type safety, immutability, defaults, and
serialization in one pattern.

---

## 3. The Abstract Platform Pattern

### Pattern

All environment-specific operations hide behind an abstract interface:

```python
class PlatformInterface(ABC):
    @abstractmethod
    def move_cursor(self, x: int, y: int) -> None: ...

    @abstractmethod
    def click(self, x: int, y: int, button: str = "left") -> None: ...

    @abstractmethod
    def key_press(self, key: str) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    @abstractmethod
    def get_screen_size(self) -> tuple[int, int]: ...

    @abstractmethod
    def capture_screen(self) -> bytes: ...

    @abstractmethod
    def get_platform_name(self) -> str: ...
```

### Directory Structure

```
agent/
├── core/       ← Business logic. NEVER imports platform modules.
├── platform/   ← OS-specific. ONLY implements PlatformInterface.
│   ├── interface.py  ← ABC + factory
│   ├── windows.py    ← Win32 implementation
│   ├── linux.py      ← X11 implementation
│   └── macos.py      ← CGEvent implementation
└── models/     ← Data models. No logic.
```

### Testing with Mocks

```python
class MockPlatform(PlatformInterface):
    def __init__(self):
        self.cursor_moves: list[tuple[int, int]] = []
        self.clicks: list[tuple[int, int, str]] = []
        self.keys_pressed: list[str] = []

    def move_cursor(self, x: int, y: int) -> None:
        self.cursor_moves.append((x, y))

    def click(self, x: int, y: int, button: str = "left") -> None:
        self.clicks.append((x, y, button))
```

### Universal Application

| Domain | Platform Interface | Implementations |
|--------|-------------------|-----------------|
| GUI agent | Mouse/keyboard ops | Win32, X11, CGEvent |
| Web agent | HTTP operations | requests, httpx, selenium |
| Database agent | Query operations | PostgreSQL, MySQL, SQLite |
| Cloud agent | Infrastructure ops | AWS, GCP, Azure |

---

## 4. The Request-Response Model Pattern

### Pattern

API interactions use **typed request and response dataclasses**:

```python
@dataclass
class Tier2Request:
    image_data: str          # Base64 PNG
    screen_width: int
    screen_height: int
    context: str             # What the agent expects to see

@dataclass
class Tier2Response:
    zones: list[Zone]        # Detected UI elements
    raw_response: str        # Raw API text (for debugging)
    latency_ms: float        # How long the call took
    token_count: int         # Tokens consumed
    success: bool            # Did the call succeed?
    error: str = ""          # Error description if failed
```

### Why Every Response Includes Metadata

| Field | Purpose |
|-------|---------|
| `success` | Uniform error checking across all call types |
| `error` | Human-readable description for logging |
| `latency_ms` | Performance monitoring and budget tracking |
| `token_count` | Cost tracking |
| `raw_response` | Debugging parse failures |

### Universal Application

Any agent calling external APIs benefits from typed request/response
pairs. They enforce structure, enable logging, and make testing trivial
(return a mock response dataclass).

---

## 5. The Step-Based Execution Pattern

### Pattern

Tasks decompose into **ordered, typed steps**:

```python
@dataclass
class TaskStep:
    step_number: int
    zone_id: str             # Target: "btn_save", "__global__", "__replan__"
    zone_label: str          # Human-readable label
    action_type: str         # "click", "type_text", "key_press", etc.
    parameters: dict         # {"text": "hello"}, {"key": "ctrl+s"}, etc.
    expected_change: str     # "Save dialog opens"
    description: str         # "Click Save button"
```

### Why Steps, Not Scripts

| Approach | Pros | Cons |
|----------|------|------|
| Script (sequential code) | Simple | Untraceable, unreplayable |
| Steps (data objects) | Loggable, replayable, retryable | More structure |

Steps enable:
- **Logging**: "Step 3: [VISUAL] click → Click Documents folder → OK"
- **Retry**: Re-execute a failed step without restarting
- **Replay**: Record and replay step sequences for testing
- **Monitoring**: Track success rate per step type

---

## 6. The Error Classification Pattern

### Pattern

Errors are **classified into categories** with **recommended recovery actions**:

```python
class RecoveryAction(Enum):
    RETRY = "retry"           # Try the same step again
    REPLAN = "replan"         # Create a new plan
    REANALYZE = "reanalyze"   # Re-capture and re-analyze screen
    SKIP = "skip"             # Skip this step, continue
    ABORT = "abort"           # Stop the entire task

@dataclass
class ErrorClassification:
    error_type: str
    severity: str             # low, medium, high, critical
    recovery_action: RecoveryAction
    description: str
    should_reanalyze_canvas: bool
```

### Classification Table

| Error | Severity | Recovery | Reanalyze? |
|-------|----------|----------|------------|
| `zone_not_found` | medium | REPLAN | Yes |
| `action_failed` | low | RETRY | No |
| `brush_lost` | medium | REANALYZE | Yes |
| `timeout` | low | RETRY | No |
| `parse_error` | low | SKIP | No |
| `budget_exhausted` | critical | ABORT | No |

### The Escalation Ladder

```
RETRY → RETRY → RETRY → (exhausted) → REPLAN → REPLAN → (exhausted) → ABORT
```

### Universal Application

Any agent with multiple failure modes needs structured error
classification. Generic "catch and retry" is insufficient — different
errors need different strategies.

---

## 7. The Zone-Based Interaction Model

### Pattern

UI elements are abstracted as **zones** with uniform properties:

```python
@dataclass
class Zone:
    id: str                  # Unique identifier
    label: str               # Human-readable name
    type: ZoneType           # button, menu_item, text_field, etc.
    state: ZoneState         # enabled, disabled, focused, etc.
    bounds: Rectangle        # Position and size
    confidence: float        # Detection confidence (0-1)
    parent_id: str = ""      # Parent zone for hierarchy
    last_seen: float = 0.0   # Timestamp of last detection
```

### Why Zones

Zones **decouple** the agent's interaction model from the UI framework:

| UI Framework | Zone Equivalent |
|-------------|----------------|
| Win32 HWND | Zone with bounds and type |
| HTML DOM element | Zone with id and state |
| Qt QWidget | Zone with label and type |
| Android View | Zone with bounds and state |
| Game UI element | Zone with label and bounds |

### Zone Registry (Thread-Safe)

```python
class ZoneRegistry:
    """Thread-safe registry of all detected zones."""

    def register(self, zone: Zone) -> None: ...
    def get(self, zone_id: str) -> Zone | None: ...
    def find_at_point(self, x: int, y: int) -> list[Zone]: ...
    def find_by_label(self, label: str) -> list[Zone]: ...
    def replace_all(self, zones: list[Zone]) -> None: ...
    def expire_stale(self, max_age_seconds: float) -> list[Zone]: ...
```

---

## 8. The Event-Driven Observation Pattern

### Pattern

Observation components **emit events** without acting on them:

```python
class ZoneTracker:
    """Tracks cursor-to-zone spatial events."""

    def update(self, cursor_x, cursor_y, timestamp) -> list[SpatialEvent]:
        # Returns events: zone_enter, zone_exit, zone_hover
        # Does NOT act on events — just observes and records
        ...
```

### Event Types

| Event | Trigger | Data |
|-------|---------|------|
| `zone_enter` | Cursor enters a zone | zone_id, position |
| `zone_exit` | Cursor leaves a zone | zone_id, duration |
| `zone_hover` | Cursor stays in zone > threshold | zone_id, hover_ms |

### Why Separation Matters

- **Testability**: Test observation logic independently from action logic
- **Replay**: Record events for debugging without replaying actions
- **Composability**: Different consumers can react to the same events

---

## 9. The Replay Buffer Pattern

### Pattern

Record every action and observation for later analysis:

```python
class ReplayBuffer:
    def start_session(self, task_description, screen_size) -> str: ...
    def record_frame(self, image, cursor_x, cursor_y, timestamp) -> None: ...
    def record_event(self, event) -> None: ...
    def stop_session(self) -> str: ...  # Returns session directory path
```

### Why Replay

| Use Case | Benefit |
|----------|---------|
| Debugging failures | See exactly what the agent saw and did |
| Training data | Use recorded sessions to improve the agent |
| Audit trail | Compliance and accountability |
| Regression testing | Replay known sessions to verify behavior |

---

## 10. The Mock-Everything Testing Pattern

### Pattern

Every external dependency is mockable. Tests are fast, deterministic,
and isolated from hardware.

### CIU Agent Test Configuration

```python
# Test settings — no delays, no real operations
settings = Settings(step_delay_seconds=0.0)

# Mock platform — records calls without touching hardware
platform = MockPlatform()

# Mock API responses — deterministic JSON
planner = MockPlanner(plan=TaskPlan(steps=[...], success=True))
```

### Results

- **931 tests** run in **<4 seconds**
- **Zero real API calls** — all mocked with deterministic responses
- **Zero real screen captures** — MockPlatform returns synthetic data
- **Zero real cursor movement** — MockPlatform records calls

### Universal Application

Agent systems are notoriously hard to test because they interact with
the real world. The mock-everything pattern makes them testable by
replacing every external dependency with a recordable mock.

---

## 11. The Structured Logging Pattern

### Pattern

Every decision point has a **structured log message** with quantitative data:

```python
# Plan creation — includes mode breakdown
logger.info(
    "Plan created: %d steps (%d visual, %d global, %d replan), success=%s",
    len(plan.steps), visual_count, global_count, replan_count, plan.success,
)

# Step execution — includes mode and action
logger.info("step %d: global key_press %r", step.step_number, key)

# Recapture — includes zone count
logger.info("Re-capture complete: %d zones detected", zone_count)

# Degradation — includes what was preserved
logger.warning(
    "Re-capture returned 0 zones (parse failure?) — keeping %d existing zones",
    registry.count,
)
```

### Key Log Points

| Component | Log Level | What It Logs |
|-----------|-----------|-------------|
| Director | INFO | Plan creation, step execution, replanning |
| Director | WARNING | Budget approaching limit |
| Director | ERROR | Step failure, replan failure |
| StepExecutor | INFO | Each step execution with mode and action |
| Recapture | INFO | Zone count after recapture |
| Recapture | WARNING | Parse failure, zone preservation |
| Tier2Analyzer | ERROR | JSON parse failure |

---

## 12. The Prompt Engineering Pattern

### Pattern

System prompts are structured code, not casual instructions:

```python
_SYSTEM_PROMPT = (
    "=== MANDATORY RULES ===\n"
    "RULE 1: If a zone exists matching the target, MUST use its zone_id.\n"
    "RULE 2: For EVERY click, use the zone_id of the target element.\n"
    "\n"
    "=== METHODOLOGY ===\n"
    "1. EXAMINE: Review all zones.\n"
    "2. IDENTIFY: Determine OS and visible applications.\n"
    "\n"
    "=== OUTPUT FORMAT ===\n"
    "Return ONLY a JSON array...\n"
    "\n"
    "=== EXAMPLES ===\n"
    "Example 1 — Clicking a visible Start button:\n"
    '  {"step_number": 1, "zone_id": "zone_start_btn", ...}\n'
    "\n"
    "=== GUIDELINES ===\n"
    "- Keep plans short...\n"
)
```

### Prompt Structure

| Section | Purpose |
|---------|---------|
| **RULES** | Mandatory constraints (caps, numbered) |
| **METHODOLOGY** | Step-by-step reasoning process |
| **FORMAT** | Exact JSON schema for output |
| **EXAMPLES** | Concrete examples for each case |
| **GUIDELINES** | Soft preferences and tips |

### Prompt Evolution Through Testing

1. **Observe** agent behavior in live test
2. **Identify** prompt weakness (e.g., agent ignores visual mode)
3. **Strengthen** prompt with explicit rules and examples
4. **Test** again to verify improvement
5. **Repeat** until behavior is correct

---

## 13. The Factory Function Pattern

### Pattern

One function constructs all components in dependency order:

```python
def build_agent(api_key: str, settings: Settings | None = None) -> CIUAgent:
    """Create all components and return a fully wired agent."""
    settings = settings or Settings()

    # Construct in dependency order
    platform = create_platform()
    capture_engine = CaptureEngine(platform, settings)
    registry = ZoneRegistry()
    # ... 14 more components ...

    # Closures for callbacks
    def _recapture() -> int:
        frame = capture_engine.capture_to_buffer()
        # ... uses tier2, registry from enclosing scope
        return len(resp.zones)

    director = Director(planner=task_planner, step_executor=step_executor,
                       recapture_fn=_recapture, settings=settings)

    return CIUAgent(platform=platform, director=director, ...)
```

### Why Not a DI Framework

- **Explicit is better than implicit** — the entire dependency graph
  is visible in one function
- **No magic** — no annotations, no container, no runtime resolution
- **17 components** is small enough for a factory function

---

## 14. The Idempotent Shutdown Pattern

### Pattern

`shutdown()` is safe to call multiple times:

```python
def shutdown(self) -> None:
    """Stop the replay session if one is active. Safe to call multiple times."""
    if self._replay_active:
        try:
            session_dir = self.replay.stop_session()
            self._replay_active = False
        except RuntimeError:
            self._replay_active = False
```

### Why Idempotent

Agents run in unpredictable environments:
- Exceptions may trigger cleanup at unexpected times
- Signal handlers may call shutdown
- `finally` blocks may call shutdown after a crash
- Users may interrupt and restart

Idempotent shutdown means: **calling it twice is exactly as safe as
calling it once.**

---

## Summary

| # | Pattern | Core Idea |
|---|---------|-----------|
| 1 | Component Graph | DAG of single-responsibility components |
| 2 | Settings Dataclass | Frozen, immutable, with defaults |
| 3 | Abstract Platform | Interface separates WHAT from HOW |
| 4 | Request-Response Models | Typed I/O with metadata |
| 5 | Step-Based Execution | Tasks = ordered, typed steps |
| 6 | Error Classification | Different errors → different recovery |
| 7 | Zone-Based Interaction | Uniform UI element abstraction |
| 8 | Event-Driven Observation | Observe without acting |
| 9 | Replay Buffer | Record everything for debugging |
| 10 | Mock-Everything Testing | Fast, deterministic, isolated |
| 11 | Structured Logging | Quantitative data at every decision |
| 12 | Prompt Engineering | Structured prompts with rules/examples |
| 13 | Factory Function | One place to wire all components |
| 14 | Idempotent Shutdown | Safe to call multiple times |

---

## Related Documents

- [AGENT_PHILOSOPHY.md](AGENT_PHILOSOPHY.md) — Design principles
- [TOKEN_BUDGET.md](TOKEN_BUDGET.md) — API economics
- [ADAPTIVE_REPLANNING.md](ADAPTIVE_REPLANNING.md) — Replanning architecture
- [DUAL_MODE_EXECUTION.md](DUAL_MODE_EXECUTION.md) — Visual vs command mode
- [PERMISSIONS_MANAGEMENT.md](PERMISSIONS_MANAGEMENT.md) — Team roles
- [architecture.md](architecture.md) — System architecture
