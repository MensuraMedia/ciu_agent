# Dual-Mode Execution Architecture

> How autonomous agents combine visual interaction (mouse cursor movement
> to detected UI elements) with command execution (keyboard shortcuts)
> for complete interface mastery. Universally applicable to any agent
> that operates on a real or virtual interface.

---

## Table of Contents

1. [Why Dual Mode?](#1-why-dual-mode)
2. [Visual Mode — The Cursor as Brush](#2-visual-mode--the-cursor-as-brush)
3. [Command Mode — The Keyboard as Efficiency](#3-command-mode--the-keyboard-as-efficiency)
4. [The Five Mandatory Rules](#4-the-five-mandatory-rules)
5. [The Planner's Decision Process](#5-the-planners-decision-process)
6. [Visual Mode Execution Pipeline](#6-visual-mode-execution-pipeline)
7. [Command Mode Execution Pipeline](#7-command-mode-execution-pipeline)
8. [Mode Selection Statistics](#8-mode-selection-statistics)
9. [Universal Application](#9-universal-application)
10. [Debugging and Observability](#10-debugging-and-observability)
11. [The Startup Signal](#11-the-startup-signal--cursor-circle-animation)

---

## 1. Why Dual Mode?

### The Problem with Single-Mode Agents

**Mouse-only agents** are crippled:
- Cannot press Ctrl+S, Alt+F4, Win+R, or any keyboard shortcut
- Cannot type text efficiently (must click each key on virtual keyboard?)
- Cannot navigate menus via hotkeys
- Slow for repetitive operations

**Keyboard-only agents** are invisible:
- User cannot see what the agent is doing
- No visual feedback — text goes to wrong field if focus was lost
- Cannot click custom UI controls that have no keyboard shortcut
- Cannot interact with canvas-based applications (drawing, games)
- Cannot right-click, drag-and-drop, or scroll to specific elements

### The CIU Solution

**CIU (Complete Interface Usage)** agents use **both modes together**:

```
┌──────────────────────────────────────────────────────────┐
│                    CIU DUAL MODE                         │
│                                                          │
│   ┌─────────────────┐      ┌─────────────────────────┐  │
│   │  VISUAL MODE    │      │  COMMAND MODE            │  │
│   │                 │      │                          │  │
│   │  zone_id from   │      │  zone_id = "__global__"  │  │
│   │  detected zones │      │                          │  │
│   │                 │      │  key_press: shortcuts     │  │
│   │  Cursor moves   │      │  type_text: text entry   │  │
│   │  to target zone │      │  No cursor movement      │  │
│   │                 │      │                          │  │
│   │  User SEES the  │      │  Efficient, fast,        │  │
│   │  cursor travel  │      │  deterministic           │  │
│   └─────────────────┘      └─────────────────────────┘  │
│                                                          │
│   Use visual when: zone exists for the target            │
│   Use command when: keyboard shortcut, no visible target │
└──────────────────────────────────────────────────────────┘
```

### Real-World Analogy

Think of how a human uses a computer:
- **Click the File menu** (visual — eyes find menu, hand moves mouse)
- **Press Ctrl+S** (command — fingers press keys, no mouse needed)
- **Click the search box** (visual — eyes find box, hand moves mouse)
- **Type "notepad"** (command — fingers type, field already focused)
- **Click the search result** (visual — eyes find result, hand clicks)

A human naturally alternates between modes. The CIU Agent does the same.

---

## 2. Visual Mode — The Cursor as Brush

### When It's Used

Visual mode is used when the planner selects a **zone_id** from the
detected zone list (anything other than `__global__` or `__replan__`).

### What Happens

1. **StepExecutor** looks up the zone in the ZoneRegistry
2. Gets the zone's center coordinates `(cx, cy)`
3. Passes the action to **BrushController**
4. BrushController calls **MotionPlanner** to generate a smooth trajectory
5. **Platform.move_cursor()** moves the OS cursor along the trajectory
6. **ZoneTracker** confirms the cursor reached the target zone
7. **ActionExecutor** performs the action (click, type, etc.)
8. User **sees the cursor physically travel** to the target

### Why It Matters

| Benefit | Description |
|---------|-------------|
| **Visual feedback** | User sees what the agent is doing |
| **Debuggability** | If cursor goes to wrong place, you can see it |
| **Trust** | User can verify the agent is clicking the right button |
| **Screencast-ability** | Recordings show meaningful cursor movement |
| **Focus management** | Clicking a field guarantees it's focused |
| **Zone verification** | BrushController verifies cursor reached the zone |

### Supported Actions in Visual Mode

| Action | Description | Example |
|--------|-------------|---------|
| `click` | Move cursor to zone center, click | Click "Save" button |
| `double_click` | Move cursor to zone, double-click | Open a file |
| `type_text` | Move to zone, click to focus, type | Type in a text field |
| `scroll` | Move to zone, scroll | Scroll a list |
| `move` | Move cursor to zone without clicking | Hover over element |

---

## 3. Command Mode — The Keyboard as Efficiency

### When It's Used

Command mode is used when the planner selects `zone_id = "__global__"`.
This means the action targets no specific zone — it's a keyboard-only
operation.

### What Happens

1. **StepExecutor** recognizes `__global__` zone_id
2. Calls `_execute_global()` instead of BrushController
3. Dispatches by action type:
   - `key_press` → `platform.key_press(key)`
   - `type_text` → `platform.type_text(text)`
   - `click` → `platform.click(x, y, button)` (rare, raw coordinates)
4. **No cursor movement**, no zone lookup, no motion planning

### Implementation

```python
def _execute_global(self, step: TaskStep, action_type: ActionType,
                    timestamp: float) -> StepResult:
    try:
        if action_type == ActionType.KEY_PRESS:
            key = step.parameters.get("key")
            self._platform.key_press(key)
        elif action_type == ActionType.TYPE_TEXT:
            text = step.parameters.get("text")
            self._platform.type_text(text)
        elif action_type == ActionType.CLICK:
            x, y = step.parameters.get("x"), step.parameters.get("y")
            self._platform.click(int(x), int(y),
                                 step.parameters.get("button", "left"))
    except Exception as exc:
        return StepResult(step=step, success=False, error=str(exc), ...)
    return StepResult(step=step, success=True, ...)
```

### When Command Mode Is Appropriate

| Scenario | Key | Example |
|----------|-----|---------|
| Open Start menu | `win` | No visible "Start" zone |
| Save file | `ctrl+s` | Keyboard shortcut faster than File→Save |
| Close application | `alt+f4` | Universal close shortcut |
| Confirm dialog | `enter` | Default button activation |
| Cancel dialog | `escape` | Universal cancel |
| Select all | `ctrl+a` | Before typing replacement text |
| Switch windows | `alt+tab` | Window management |
| Type search text | text | Search box already focused |
| Type in editor | text | Editor already focused |

---

## 4. The Five Mandatory Rules

These rules are embedded in the TaskPlanner system prompt and control
the planner's mode selection:

### RULE 1: Zone Matching

> If a zone exists in the zone list that matches the element you want
> to interact with, you MUST use that zone's id. Do NOT use `__global__`
> when a matching zone is available.

**Rationale**: Forces visual mode whenever possible, ensuring the cursor
physically moves to UI elements.

**Example violation**: Taskbar zone exists → planner uses `__global__`
key_press "win" instead of clicking the taskbar zone.

### RULE 2: Click Targeting

> For EVERY click action, use the zone_id of the target element. The
> agent needs zone_id to navigate the cursor there.

**Rationale**: A click without a zone_id means the cursor doesn't move.
The click happens wherever the cursor currently is.

### RULE 3: Text Input Pattern

> For text input into a visible text field, FIRST click the text field
> zone (visual mode), THEN type_text.

**Rationale**: Ensures the correct field is focused before typing.
Prevents text going to the wrong field.

```json
{"step_number": 1, "zone_id": "search_box_10", "action_type": "click",
 "description": "Click search box to focus it"},
{"step_number": 2, "zone_id": "__global__", "action_type": "type_text",
 "parameters": {"text": "notepad"},
 "description": "Type search query"}
```

### RULE 4: __global__ Restrictions

> Only use `__global__` for:
> - Keyboard shortcuts (Ctrl+S, Alt+F4, Win+R, Enter, Tab)
> - Typing text when the target field is already focused
> - OS-level actions with no visible UI target

**Rationale**: Limits command mode to genuinely keyboard-only operations.

### RULE 5: Replan After Transitions

> After steps that change the screen significantly, insert a
> `__replan__` step.

**Rationale**: Ensures the agent re-observes the world and gets fresh
zones before continuing.

---

## 5. The Planner's Decision Process

### Input

The planner receives:
1. **Task description**: "Open Notepad and type hello"
2. **OS information**: "Windows"
3. **Zone list with IDs**: Each zone has id, label, type, state, center

### Decision Tree

```
For each step needed:
     │
     ├── Is there a zone matching the target?
     │    ├── YES → Use zone_id (VISUAL MODE)
     │    │         Action: click, double_click, type_text, scroll
     │    │
     │    └── NO → Is this a keyboard shortcut?
     │              ├── YES → Use __global__ (COMMAND MODE)
     │              │         Action: key_press
     │              │
     │              └── Is the target field already focused?
     │                   ├── YES → Use __global__ type_text
     │                   └── NO → Wait for replan with new zones
     │
     ├── Will this step change the screen significantly?
     │    └── YES → Add __replan__ step after this one
     │
     └── Done
```

### Prompt Reinforcement

The prompt includes multiple reinforcements:

```
AVAILABLE ZONES (use these zone_ids for visual mode):
- id=file_0  label="File"  type=menu_item  state=enabled  center=(45, 20)
- id=search_box_10  label="Search box"  type=text_field  center=(790, 15)
...

REMINDER: You MUST use zone_id from the list above for any element you
want to click or interact with. Only use "__global__" for keyboard
shortcuts with no visible target.
```

---

## 6. Visual Mode Execution Pipeline

### Full Pipeline

```
TaskStep {zone_id: "btn_save", action_type: "click"}
     │
     ▼
StepExecutor.execute()
     │
     ├── 1. Map action_type string → ActionType enum
     ├── 2. Verify zone_id in ZoneRegistry
     ├── 3. Get zone bounds and center (cx, cy)
     ├── 4. Build Action object
     │
     ▼
BrushController.execute_action(zone, action)
     │
     ├── 5. MotionPlanner.plan_motion(current_pos → zone_center)
     │       └── Generates smooth trajectory (ease-in/out, bezier)
     │
     ├── 6. For each point in trajectory:
     │       └── Platform.move_cursor(x, y)
     │           └── OS physically moves the cursor
     │
     ├── 7. ZoneTracker detects zone_enter event
     │       └── Confirms cursor reached the target zone
     │
     ├── 8. ActionExecutor.execute(action)
     │       └── Platform.click(cx, cy, "left")
     │           └── OS performs the click
     │
     └── 9. Return BrushActionResult → StepResult
```

### Motion Planning

The MotionPlanner generates smooth, human-like cursor trajectories:

```python
motion_speed_pixels_per_sec: float = 1500.0  # Default cursor speed
```

The cursor doesn't teleport — it **travels** from its current position
to the target zone, creating visible mouse movement that the user can
follow.

---

## 7. Command Mode Execution Pipeline

### Full Pipeline

```
TaskStep {zone_id: "__global__", action_type: "key_press",
          parameters: {"key": "ctrl+s"}}
     │
     ▼
StepExecutor.execute()
     │
     ├── 1. Map action_type string → ActionType enum
     ├── 2. Detect __global__ zone_id
     │
     ▼
StepExecutor._execute_global()
     │
     ├── 3. Dispatch by action_type:
     │       ├── KEY_PRESS → platform.key_press("ctrl+s")
     │       ├── TYPE_TEXT → platform.type_text("hello world")
     │       └── CLICK → platform.click(x, y, button)
     │
     └── 4. Return StepResult(success=True)
```

### No Motion, No Zone, No Tracking

Command mode skips the entire BrushController pipeline:
- No MotionPlanner trajectory generation
- No cursor movement
- No ZoneTracker events
- No zone verification

This makes it **fast** (milliseconds) but **invisible** (user sees
nothing happening).

---

## 8. Mode Selection Statistics

### From Live Tests

**Plan 1 — Desktop to Start menu (no app-specific zones):**
| Step | Mode | Action | Why |
|------|------|--------|-----|
| 1 | `__global__` | Win key | No Start button zone detected |
| 2 | `__global__` | Type "notepad" | Search field focused by Win key |
| 3 | `__global__` | Enter | Keyboard shortcut |
| 4 | `__replan__` | Replan | App about to open |

**Plan 2 — Notepad open (app zones detected):**
| Step | Mode | Action | Why |
|------|------|--------|-----|
| 1 | **VISUAL** | Click editor | Editor zone detected |
| 2 | `__global__` | Type text | Field focused by click |
| 3 | `__global__` | Ctrl+S | Keyboard shortcut |
| 4 | `__replan__` | Replan | Save dialog about to open |

**Plan 3 — Save dialog (dialog zones detected):**
| Step | Mode | Action | Why |
|------|------|--------|-----|
| 1 | **VISUAL** | Click Documents folder | Folder zone detected |
| 2 | **VISUAL** | Click filename field | Text field zone detected |
| 3 | `__global__` | Ctrl+A | Select all (shortcut) |
| 4 | `__global__` | Type filename | Field focused |
| 5 | **VISUAL** | Click Save button | Button zone detected |

### Pattern

- **Desktop/OS-level**: Mostly command mode (no specific zones)
- **Application interaction**: Mix of visual and command
- **Dialog interaction**: Mostly visual mode (buttons, fields, folders detected)
- **Visual mode increases** as the agent interacts with app-specific UI

---

## 9. Universal Application

### Web Automation

| Visual Equivalent | Command Equivalent |
|-------------------|-------------------|
| Click DOM element by selector | Navigate to URL |
| Click button by ID | Submit form with Enter |
| Select dropdown option | Tab between fields |
| Drag and drop | Keyboard shortcuts (Ctrl+A, Ctrl+C) |

### Mobile Automation

| Visual Equivalent | Command Equivalent |
|-------------------|-------------------|
| Tap UI element | Swipe gestures |
| Long press button | Volume buttons |
| Scroll to element | System back button |
| Pinch to zoom | Accessibility shortcuts |

### Game AI

| Visual Equivalent | Command Equivalent |
|-------------------|-------------------|
| Click game UI element | Hotkey actions (1-9) |
| Click on map location | WASD movement |
| Click inventory item | Tab to switch modes |
| Click dialogue option | Space to continue |

### Robotic Process Automation (RPA)

| Visual Equivalent | Command Equivalent |
|-------------------|-------------------|
| Click ERP button | Function key shortcuts |
| Select dropdown value | Tab-Enter navigation |
| Click report link | Ctrl+P to print |
| Click checkbox | Space to toggle |

---

## 10. Debugging and Observability

### Step Logging

Every step logs its mode:

```
13:23:05 [INFO] step 1: global key_press 'win'
13:23:37 [INFO] step 2: global type_text (7 chars)
13:24:07 [INFO] step 1: [VISUAL] click zone 'editor_area_5'
```

### Plan Composition Logging

The Director logs the mode breakdown per plan:

```
13:20:21 [INFO] Plan created: 4 steps (0 visual, 3 global, 1 replan), success=True
13:23:05 [INFO] Plan created: 4 steps (1 visual, 2 global, 1 replan), success=True
13:39:08 [INFO] Plan created: 5 steps (3 visual, 2 global, 0 replan), success=True
```

### Result Summary

```python
for sr in result.step_results:
    mode = 'VISUAL' if sr.step.zone_id not in ('__global__', '__replan__') else sr.step.zone_id
    print(f"Step {sr.step.step_number}: [{mode}] {sr.step.action_type} | {sr.step.description}")
```

---

## 11. The Startup Signal — Cursor Circle Animation

### Purpose

Before any task execution, the agent draws a visible circle at screen
center with the cursor. This signals to the user:

> "The CIU Agent has taken control of the mouse. Watch the cursor."

### Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Center | Screen center (w/2, h/2) | Adapts to any resolution |
| Radius | 80 pixels | Visible but not disruptive |
| Loops | 2 | Two full circles |
| Steps per loop | 50 | Smooth motion |
| Delay per step | 15ms | ~1.5s per loop |
| Total duration | ~3 seconds | Quick but noticeable |

### Implementation

```python
def _signal_control(self) -> None:
    if self.settings.step_delay_seconds == 0:
        return  # Skip in tests

    w, h = self.platform.get_screen_size()
    cx, cy = w // 2, h // 2

    self.platform.move_cursor(cx, cy)
    time.sleep(0.15)

    for _ in range(2):  # 2 loops
        for i in range(51):
            angle = 2.0 * math.pi * i / 50
            x = int(cx + 80 * math.cos(angle))
            y = int(cy + 80 * math.sin(angle))
            self.platform.move_cursor(x, y)
            time.sleep(0.015)

    self.platform.move_cursor(cx, cy)
```

### Skip in Tests

The animation is skipped when `step_delay_seconds == 0`, which is the
standard test configuration. This prevents 3-second delays in the
931-test suite.

---

## Related Documents

- [AGENT_PHILOSOPHY.md](AGENT_PHILOSOPHY.md) — Core design principles
- [ADAPTIVE_REPLANNING.md](ADAPTIVE_REPLANNING.md) — Replanning architecture
- [TOKEN_BUDGET.md](TOKEN_BUDGET.md) — API token economics
- [DEVELOPMENT_PATTERNS.md](DEVELOPMENT_PATTERNS.md) — Code patterns
- [PERMISSIONS_MANAGEMENT.md](PERMISSIONS_MANAGEMENT.md) — Team roles
- [architecture.md](architecture.md) — System architecture
