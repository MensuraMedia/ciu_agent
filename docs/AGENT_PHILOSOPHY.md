# Agent Philosophy and Design Principles

> A universal guide to building autonomous agents — extracted from the CIU
> (Complete Interface Usage) Agent project but applicable to any agent-based
> application, process automation, or AI-driven system.

---

## Table of Contents

1. [The Canvas-Brush Metaphor](#1-the-canvas-brush-metaphor)
2. [Complete Interface Usage (CIU) Principle](#2-complete-interface-usage-ciu-principle)
3. [Dependency Injection and No Global State](#3-dependency-injection-and-no-global-state)
4. [Three-Tier Analysis Architecture](#4-three-tier-analysis-architecture)
5. [Adaptive Replanning Over Fixed Plans](#5-adaptive-replanning-over-fixed-plans)
6. [Graceful Degradation and Zone Preservation](#6-graceful-degradation-and-zone-preservation)
7. [The Signal-Before-Act Principle](#7-the-signal-before-act-principle)
8. [Modularity and Composition](#8-modularity-and-composition)
9. [Cross-Platform by Architecture](#9-cross-platform-by-architecture-not-by-abstraction)
10. [Testing as a First-Class Concern](#10-testing-as-a-first-class-concern)

---

## 1. The Canvas-Brush Metaphor

### Core Concept

The CIU Agent treats every computing environment through a single
powerful metaphor:

| Metaphor    | Real-World Mapping                          |
|-------------|---------------------------------------------|
| **Canvas**  | The screen — the observable surface          |
| **Brush**   | The cursor — the agent's primary actuator    |
| **Zones**   | UI elements — clickable, typeable, scrollable regions |
| **Strokes** | Actions — clicks, keystrokes, scrolls, drags |

This metaphor is not decorative — it is **architectural**. Every
component in the system maps to one of these concepts:

```
CaptureEngine  → reads the canvas
CanvasMapper   → identifies zones on the canvas
BrushController → moves the brush and applies strokes
ZoneTracker    → observes where the brush is relative to zones
Director       → decides which zones to target and which strokes to apply
```

### The Four-Phase Cycle: Observe → Map → Act → Verify

Every agent operation follows this cycle:

```
    ┌─────────────┐
    │   OBSERVE   │ ← Capture the current screen state
    │  (Tier 0-2) │
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │     MAP     │ ← Identify and locate all interactive zones
    │  (Zones)    │
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │     ACT     │ ← Move cursor to zone, perform action
    │  (Brush)    │
    └──────┬──────┘
           │
    ┌──────▼──────┐
    │   VERIFY    │ ← Re-observe, confirm expected change occurred
    │  (Diff)     │
    └──────┬──────┘
           │
           └──────→ (loop back to OBSERVE)
```

**The agent never assumes.** It always observes first, maps what it
sees, acts on the map, then verifies the outcome. If verification
fails, the cycle restarts with fresh observation.

### Universal Application

This metaphor maps cleanly to other domains:

| Domain              | Canvas         | Brush           | Zones                    |
|---------------------|----------------|-----------------|--------------------------|
| GUI automation      | Screen pixels  | Mouse cursor    | Buttons, menus, fields   |
| Web automation      | DOM tree       | HTTP client     | Elements, forms, links   |
| Robotics            | Sensor data    | Actuators       | Objects, surfaces, paths |
| Mobile testing      | Touch screen   | Touch events    | Tap targets, gestures    |
| CLI automation      | Terminal output | Stdin pipe      | Prompts, commands, flags |
| API orchestration   | Response data  | HTTP requests   | Endpoints, fields, errors|
| Game AI             | Game state     | Controller input| Characters, items, menus |
| Document processing | Page content   | Edit operations | Paragraphs, tables, fields|

**Key insight:** Any system where an agent must *observe an environment*,
*identify interactive elements*, and *perform actions* on those elements
fits the canvas-brush model. The metaphor provides a universal vocabulary
for discussing agent architecture.

### Anti-Pattern: The Blind Actor

An agent that acts without observing is a **blind actor**:

```python
# WRONG — blind actor
def open_notepad():
    press_key("win")        # Hope the Start menu opens
    time.sleep(2)           # Hope 2 seconds is enough
    type_text("notepad")    # Hope the search box is focused
    press_key("enter")      # Hope Notepad is the top result

# RIGHT — observe-map-act-verify
def open_notepad(agent):
    agent.observe()                        # Capture screen
    zones = agent.map()                    # Detect all zones
    start = find_zone(zones, "Start")      # Find Start button
    agent.act(click=start)                 # Click it (visual)
    agent.verify("Start menu opens")       # Confirm change
    agent.observe()                        # Capture new state
    # ... continue with fresh zones
```

The blind actor uses fixed delays and assumes outcomes. The
observe-map-act-verify agent confirms every state transition
before proceeding.

---

## 2. Complete Interface Usage (CIU) Principle

### Definition

**CIU** stands for **Complete Interface Usage**. This means the agent
must be capable of using *every input method* available to a human user:

- **Mouse cursor** — point, click, double-click, right-click, drag
- **Keyboard** — type text, press shortcuts, modifier keys, function keys
- **Scroll** — scroll wheels, scroll bars, page up/down
- **Context menus** — right-click menus, long-press menus
- **Drag and drop** — file operations, UI rearrangement
- **System-level actions** — Alt+Tab, Win+R, Ctrl+Alt+Delete

### The Dual Mode Philosophy

CIU requires two execution modes that work together:

```
┌─────────────────────────────────────────────────┐
│               DUAL MODE EXECUTION               │
├────────────────────┬────────────────────────────┤
│   VISUAL MODE      │   COMMAND MODE             │
│                    │                            │
│ • Uses zone_id     │ • Uses "__global__"        │
│ • Cursor moves     │ • No cursor movement       │
│ • User sees action │ • Keyboard shortcuts       │
│ • Click, type in   │ • OS-level actions         │
│   visible elements │ • Text entry when field    │
│                    │   is already focused       │
│                    │                            │
│ WHEN: zone exists  │ WHEN: no matching zone     │
│ for the target     │ or keyboard-only action    │
└────────────────────┴────────────────────────────┘
```

### Why Both Modes Are Mandatory

**Visual-only agents** are crippled:
- Cannot press keyboard shortcuts (Ctrl+S, Alt+F4, Win+R)
- Cannot type into focused fields efficiently
- Cannot use hotkeys to navigate faster than clicking
- Slow for repetitive operations

**Command-only agents** are invisible:
- User cannot see what the agent is doing
- No visual feedback — typing goes to wrong field if focus is lost
- Cannot discover UI elements (must know exact shortcuts)
- Cannot interact with custom UI controls that have no keyboard shortcuts

**CIU agents** use both:
- Click buttons visually (user sees cursor move)
- Use keyboard shortcuts for efficiency (Ctrl+S instead of File → Save)
- Type into fields after visually clicking to focus them
- Recover from focus loss by visually re-clicking the target

### The Five Mandatory Rules

These rules ensure the planner always generates the correct mode:

| Rule | Description | Rationale |
|------|-------------|-----------|
| **1** | If a zone exists matching the target, MUST use its zone_id | Forces visual mode when possible |
| **2** | For every click action, use the zone_id of the target | Cursor must physically navigate there |
| **3** | For text input, first click the field zone, then type | Ensures correct field is focused |
| **4** | `__global__` only for shortcuts with no visible target | Limits command mode to keyboard-only actions |
| **5** | After major screen changes, insert `__replan__` step | Ensures fresh zones for the next segment |

### Universal Application

The CIU principle applies beyond GUI automation:

- **API agents**: Use both REST endpoints (visual: specific, targeted) and
  batch operations (command: bulk, efficient)
- **DevOps agents**: Use both UI dashboards (visual: monitoring, debugging)
  and CLI tools (command: deployment, scaling)
- **Data agents**: Use both visual data explorers (visual: discovery,
  verification) and SQL queries (command: bulk processing)

**The principle:** An agent that can only use ONE interface method is
fundamentally limited. Complete interface usage means mastering ALL
available interaction methods.

---

## 3. Dependency Injection and No Global State

### The Core Rule

> Every component receives its dependencies through the constructor.
> No singletons. No global variables. No module-level mutable state.

```python
# WRONG — global state
_registry = ZoneRegistry()  # Module-level singleton

class Director:
    def __init__(self):
        self._registry = _registry  # Hidden dependency

# RIGHT — dependency injection
class Director:
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
```

### Why This Matters for Agents

| Benefit | Explanation |
|---------|-------------|
| **Testability** | Replace real APIs with mocks — 931 tests run in <4 seconds with no real screen captures or API calls |
| **Composability** | Swap components freely — different planners, different platforms, different analyzers |
| **Parallel execution** | No shared mutable state means multiple agents can run concurrently |
| **Configurability** | Different settings per instance — test settings vs production settings |
| **Debuggability** | Every dependency is explicit and traceable in the constructor |

### The Factory Function Pattern

All component construction happens in ONE place:

```python
def build_agent(api_key: str, settings: Settings | None = None) -> CIUAgent:
    """Create all components and return a fully wired CIUAgent."""
    if settings is None:
        settings = Settings()

    # 1. Platform (OS-specific)
    platform = create_platform()

    # 2. Capture Engine (needs platform)
    capture_engine = CaptureEngine(platform, settings)

    # 3. Zone Registry (shared state, thread-safe)
    registry = ZoneRegistry()

    # ... 14 more components, each receiving only what it needs ...

    # 17. Top-level agent
    return CIUAgent(
        platform=platform,
        capture_engine=capture_engine,
        registry=registry,
        # ... all components ...
        settings=settings,
    )
```

### The Settings Dataclass

Configuration is a single, frozen, immutable dataclass:

```python
@dataclass(frozen=True)
class Settings:
    """Immutable configuration for the entire CIU Agent system."""

    # Capture engine
    target_fps: int = 15
    max_fps: int = 30

    # API settings
    api_timeout_vision_seconds: float = 60.0
    api_timeout_text_seconds: float = 30.0
    api_max_retries: int = 3

    # Director
    step_delay_seconds: float = 2.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        """Create from dict. Unknown keys silently ignored."""
        known_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known_names}
        return cls(**filtered)
```

**Why frozen?** Prevents accidental mutation, is thread-safe, and makes
configuration a value object that can be passed around freely.

### Universal Application

- **Microservices**: Each service receives its dependencies via constructor
  or environment — never reaches into other services' internals
- **Plugin systems**: Plugins receive a host interface — never import the
  host's internal modules
- **ML pipelines**: Each stage receives its inputs and produces outputs —
  no shared global model state

---

## 4. Three-Tier Analysis Architecture

### The Escalation Pyramid

```
                    ┌───────────┐
                    │  TIER 2   │  Expensive: Claude API vision
                    │ (Remote)  │  ~25-55s, ~4000 tokens, $$$
                    │ Full      │  "What is everything on screen?"
                    │ analysis  │
                ┌───┴───────────┴───┐
                │      TIER 1       │  Moderate: OpenCV local
                │     (Local)       │  ~50ms, 0 tokens, $0
                │  Region analysis  │  "What changed in this region?"
            ┌───┴───────────────────┴───┐
            │          TIER 0           │  Cheap: Frame differencing
            │         (Local)           │  ~1ms, 0 tokens, $0
            │     Frame comparison      │  "Did anything change?"
            └───────────────────────────┘
```

### The Escalation Principle

> Never use a higher tier when a lower tier suffices.

| Situation | Tier | Rationale |
|-----------|------|-----------|
| Frame identical to previous | 0 | No change detected, skip analysis |
| Small region changed (<30%) | 1 | Local OpenCV can analyze the diff |
| Large change or new app opened | 2 | Full API analysis needed |
| Initial startup | 2 | No prior data, need full analysis |

### Cost Awareness

Every Tier 2 API call costs:
- **Time**: 25-55 seconds of latency
- **Money**: ~4000 tokens × API pricing
- **Reliability**: ~10-15% chance of parse failure

The three-tier architecture ensures the agent is **frugal** — it only
calls the expensive API when the cheaper tiers cannot provide enough
information.

### Universal Application

| Domain | Tier 0 | Tier 1 | Tier 2 |
|--------|--------|--------|--------|
| **Video surveillance** | Motion detection | Object detection (local) | Full scene analysis (cloud) |
| **Document processing** | Checksum comparison | Keyword extraction | Full NLP comprehension |
| **Network monitoring** | Packet count delta | Protocol analysis | Deep packet inspection |
| **Code review** | File diff detection | AST analysis (local) | Full semantic analysis (LLM) |
| **Financial trading** | Price change threshold | Technical indicators | Full market sentiment analysis |

---

## 5. Adaptive Replanning Over Fixed Plans

### Plans Are Hypotheses, Not Contracts

A plan created from the initial screen state becomes stale after the
first step. The screen changes — new windows open, dialogs appear,
menus expand — and the plan's assumptions no longer hold.

```
FIXED PLAN (fragile):
  1. Press Win key        → assumes Start menu opens
  2. Type "notepad"       → assumes search box is focused
  3. Press Enter          → assumes Notepad is top result
  4. Type "hello world"   → assumes Notepad is open and focused
  5. Press Ctrl+S         → assumes text was typed correctly
  ... entire plan created before step 1 executes

ADAPTIVE PLAN (resilient):
  Plan A (desktop → Start menu):
    1. Press Win key
    2. Type "notepad"
    3. Press Enter
    4. __replan__          → re-capture screen, see new zones

  Plan B (Notepad open → type and save):
    1. Click editor zone   → visual mode, cursor moves
    2. Type "hello world"
    3. Ctrl+S
    4. __replan__          → re-capture screen for Save dialog

  Plan C (Save dialog → complete save):
    1. Click Documents folder  → visual mode
    2. Click filename field    → visual mode
    3. Type filename
    4. Click Save button       → visual mode
```

### The Rolling Horizon Model

```
Time ──────────────────────────────────────────────────►

Plan A          Plan B            Plan C
┌─────────┐    ┌──────────┐     ┌──────────┐
│ Steps   │    │ Steps    │     │ Steps    │
│ 1,2,3   │──►│ 1,2,3    │───►│ 1,2,3,4  │
│ replan  │    │ replan   │     │ (done)   │
└─────────┘    └──────────┘     └──────────┘
     ▲              ▲                ▲
     │              │                │
  Fresh          Fresh            Fresh
  zones          zones            zones
  (desktop)      (Notepad)        (Save dialog)
```

Each plan segment uses **fresh zones** from the most recent screen
capture. The planner only plans for what it can currently see.

### Completed Step Context

When replanning, the Director passes a list of completed step
descriptions so the planner doesn't restart from scratch:

```
=== ALREADY COMPLETED (DO NOT REPEAT) ===
  DONE 1. Press Windows key to open Start menu
  DONE 2. Type 'notepad' to search
  DONE 3. Press Enter to launch Notepad
  DONE 4. Click editor to focus

IMPORTANT: Plan ONLY the remaining steps to finish the task.
The application is already open. Do NOT reopen it.
```

### Universal Application

- **Robotics**: Plan the next few moves, execute, re-observe, replan
- **Game AI**: Plan the next few turns, execute, observe opponent, replan
- **Project management**: Plan the next sprint, execute, retrospect, replan
- **Military operations**: OODA loop (Observe, Orient, Decide, Act)

---

## 6. Graceful Degradation and Zone Preservation

### The Preservation Principle

> Partial information is better than no information.

When a Tier 2 re-capture fails (timeout, parse error, network issue),
the agent **keeps its existing zones** instead of wiping to zero:

```python
def _recapture() -> int:
    resp = tier2.analyze_sync(req)
    if resp.success and resp.zones:
        registry.replace_all(resp.zones)         # New zones: use them
        return len(resp.zones)
    if resp.success and not resp.zones:
        logger.warning(
            "Re-capture returned 0 zones (parse failure?) "
            "— keeping %d existing zones",
            registry.count,
        )
    return registry.count                         # Keep existing zones
```

### The Fallback Chain

```
┌──────────────────┐
│ Visual Mode      │ ← Preferred: click detected zones
│ (zone_id)        │
└────────┬─────────┘
         │ zone not found?
┌────────▼─────────┐
│ Command Mode     │ ← Fallback: keyboard shortcut
│ (__global__)     │
└────────┬─────────┘
         │ shortcut failed?
┌────────▼─────────┐
│ Replan           │ ← Re-observe and try a new approach
│ (__replan__)     │
└────────┬─────────┘
         │ replan failed?
┌────────▼─────────┐
│ Report & Wait    │ ← Ask user for help
│ (abort)          │
└──────────────────┘
```

### Error Classification

Not all errors are equal. The ErrorClassifier categorizes failures
and recommends specific recovery actions:

| Error Type | Recovery | Description |
|-----------|----------|-------------|
| `zone_not_found` | REPLAN | Zone was removed or screen changed |
| `action_failed` | RETRY | Click/type failed, try again |
| `brush_lost` | REANALYZE | Cursor couldn't reach target |
| `timeout` | RETRY | API or action timed out |
| `parse_error` | SKIP | Non-critical response parsing issue |
| `budget_exhausted` | ABORT | No more API calls available |

### Universal Application

- **Network services**: If primary server fails, fall back to secondary,
  then to cached data, then to error page
- **Database operations**: If write fails, retry, then queue, then alert
- **Trading systems**: If market data feed fails, use last known price,
  then pause trading, then alert operator

---

## 7. The Signal-Before-Act Principle

### Transparency in Automation

> Before taking control, signal to the user. Before acting, verify
> the state. After acting, verify the outcome.

The CIU Agent signals control by drawing a circle at screen center:

```python
def _signal_control(self) -> None:
    """Move cursor in a circle at screen center to signal control."""
    if self.settings.step_delay_seconds == 0:
        return  # Skip in test environments

    w, h = self.platform.get_screen_size()
    cx, cy = w // 2, h // 2
    radius = 80

    self.platform.move_cursor(cx, cy)
    time.sleep(0.15)

    for _ in range(2):  # 2 loops
        for i in range(51):
            angle = 2.0 * math.pi * i / 50
            x = int(cx + radius * math.cos(angle))
            y = int(cy + radius * math.sin(angle))
            self.platform.move_cursor(x, y)
            time.sleep(0.015)

    self.platform.move_cursor(cx, cy)
```

### The Three Verification Points

1. **Pre-action**: Is the target zone still where we expect it?
2. **During action**: Did the cursor reach the zone? (ZoneTracker)
3. **Post-action**: Did the expected change occur? (re-capture)

### Universal Application

- **Deployment systems**: Show banner "Deployment in progress" before acting
- **Financial systems**: Confirm order details before executing trade
- **Medical devices**: Signal alarm before changing dosage
- **Any autonomous system**: Make intent visible before executing

---

## 8. Modularity and Composition

### Single Responsibility Per Component

Each CIU Agent component has exactly ONE job:

| Component | Responsibility |
|-----------|---------------|
| `CaptureEngine` | Capture screen frames |
| `StateClassifier` | Classify frame changes (stable/changed/transitioning) |
| `Tier1Analyzer` | Local OpenCV region analysis |
| `Tier2Analyzer` | Claude API full-screen analysis |
| `CanvasMapper` | Route frames through analysis tiers |
| `ZoneRegistry` | Store and query detected zones |
| `ZoneTracker` | Track cursor-to-zone spatial events |
| `MotionPlanner` | Generate smooth cursor trajectories |
| `ActionExecutor` | Execute input actions (click, type, etc.) |
| `BrushController` | Coordinate motion + action + tracking |
| `TaskPlanner` | Decompose tasks into steps via Claude API |
| `StepExecutor` | Bridge TaskStep → BrushController |
| `ErrorClassifier` | Classify errors and recommend recovery |
| `Director` | Orchestrate plan → execute → replan loop |
| `ReplayBuffer` | Record sessions for debugging/replay |

### Composition Over Inheritance

No component inherits from another component. They **compose**:

```
Director
  ├── TaskPlanner      (plans tasks)
  ├── StepExecutor     (executes steps)
  │    ├── BrushController (moves cursor + acts)
  │    │    ├── MotionPlanner   (plans trajectories)
  │    │    ├── ActionExecutor  (clicks, types)
  │    │    └── ZoneTracker     (tracks cursor events)
  │    └── ZoneRegistry     (zone lookup)
  ├── ErrorClassifier  (classifies failures)
  └── ZoneRegistry     (read zones for planning)
```

### Universal Application

- **Microservices**: Each service has one responsibility, composes with others
- **Unix philosophy**: "Do one thing and do it well"
- **React components**: Each component renders one thing, composes into pages

---

## 9. Cross-Platform by Architecture, Not by Abstraction

### The Platform Interface

All OS-specific operations are behind an abstract base class:

```python
class PlatformInterface(ABC):
    """Abstract interface for OS-specific operations."""

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
    def get_cursor_position(self) -> tuple[int, int]: ...

    @abstractmethod
    def capture_screen(self) -> bytes: ...

    @abstractmethod
    def get_platform_name(self) -> str: ...
```

### The Separation Rule

```
ciu_agent/
├── core/           ← Business logic. NEVER imports platform modules.
│   ├── director.py
│   ├── brush_controller.py
│   ├── task_planner.py
│   └── ...
├── platform/       ← OS-specific. ONLY implements PlatformInterface.
│   ├── interface.py    ← ABC + create_platform() factory
│   ├── windows.py      ← Win32 API + ctypes + pynput
│   ├── linux.py        ← X11 + xdotool
│   └── macos.py        ← CGEvent + AppleScript
└── models/         ← Data models. No logic, no imports from core/platform.
```

### Universal Application

- **Database ORMs**: Business logic never imports `psycopg2` or `mysql` —
  uses an abstract repository interface
- **Cloud providers**: Application code never imports `boto3` or `google.cloud` —
  uses a storage interface
- **UI frameworks**: Business logic never imports React or Vue — uses
  view model interfaces

---

## 10. Testing as a First-Class Concern

### The 931-Test Standard

The CIU Agent has **931 tests** that run in under 4 seconds, with:
- **No real screen captures** — MockPlatform returns synthetic frames
- **No real API calls** — Mock HTTP responses with deterministic JSON
- **No real cursor movement** — MockPlatform records calls for assertion
- **No real delays** — `Settings(step_delay_seconds=0.0)` skips all sleeps

### Mock Everything

```python
class MockPlatform(PlatformInterface):
    """Records all calls for assertion without touching real hardware."""

    def __init__(self):
        self.cursor_moves: list[tuple[int, int]] = []
        self.clicks: list[tuple[int, int, str]] = []
        self.keys_pressed: list[str] = []
        self.text_typed: list[str] = []

    def move_cursor(self, x: int, y: int) -> None:
        self.cursor_moves.append((x, y))

    def click(self, x: int, y: int, button: str = "left") -> None:
        self.clicks.append((x, y, button))

    def key_press(self, key: str) -> None:
        self.keys_pressed.append(key)

    def type_text(self, text: str) -> None:
        self.text_typed.append(text)
```

### Test Behavior, Not Implementation

```python
# WRONG — tests implementation details
def test_director_calls_planner():
    director._planner.plan.assert_called_once()

# RIGHT — tests behavior
def test_director_creates_plan_with_steps():
    result = director.execute_task("Open Notepad")
    assert result.success
    assert result.steps_completed > 0
    assert result.plans_used >= 1
```

### Universal Application

- **Agent systems are hard to test** because they interact with the real
  world. Dependency injection + mock platforms make them testable.
- **Deterministic timing** — pass timestamps explicitly instead of calling
  `time.time()` inside components.
- **Fast feedback** — 931 tests in <4 seconds means developers run tests
  on every change.

---

## Summary Table

| # | Principle | Core Idea | Universal Rule |
|---|-----------|-----------|----------------|
| 1 | Canvas-Brush | Screen = canvas, cursor = brush | Observe → Map → Act → Verify |
| 2 | CIU | Use EVERY interface method | Don't limit to one interaction mode |
| 3 | No Global State | Inject all dependencies | Explicit > implicit |
| 4 | Three-Tier | Cheap first, expensive only if needed | Minimize costly operations |
| 5 | Adaptive Plans | Plans are hypotheses, not contracts | Re-observe and replan at transitions |
| 6 | Graceful Degradation | Partial info > no info | Always have a fallback |
| 7 | Signal-Before-Act | Show intent, verify state, confirm outcome | Transparency builds trust |
| 8 | Modularity | One job per component, compose freely | Single responsibility + composition |
| 9 | Cross-Platform | Separate WHAT from HOW | Abstract interfaces in dedicated layers |
| 10 | Testing First | Mock everything, test behavior | Fast, deterministic, isolated tests |

---

## Related Documents

- [TOKEN_BUDGET.md](TOKEN_BUDGET.md) — API token economics and optimization
- [ADAPTIVE_REPLANNING.md](ADAPTIVE_REPLANNING.md) — Replanning architecture in depth
- [DUAL_MODE_EXECUTION.md](DUAL_MODE_EXECUTION.md) — Visual vs command mode
- [DEVELOPMENT_PATTERNS.md](DEVELOPMENT_PATTERNS.md) — Code patterns for agent development
- [PERMISSIONS_MANAGEMENT.md](PERMISSIONS_MANAGEMENT.md) — Team roles and object permissions
- [architecture.md](architecture.md) — CIU Agent system architecture
