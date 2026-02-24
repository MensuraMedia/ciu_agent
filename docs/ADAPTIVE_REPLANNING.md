# Adaptive Replanning Architecture

> How autonomous agents handle changing environments by breaking tasks
> into plan segments, re-observing the world at transition points, and
> replanning with fresh data. Universally applicable to any multi-step
> autonomous system.

---

## Table of Contents

1. [The Problem with Fixed Plans](#1-the-problem-with-fixed-plans)
2. [The Rolling Horizon Model](#2-the-rolling-horizon-model)
3. [The __replan__ Step Type](#3-the-__replan__-step-type)
4. [Completed Step Tracking](#4-completed-step-tracking)
5. [The Recapture Pipeline](#5-the-recapture-pipeline)
6. [Plan Segment Lifecycle](#6-plan-segment-lifecycle)
7. [Budget Management Across Replans](#7-budget-management-across-replans)
8. [Error-Based vs Adaptive Replanning](#8-error-based-vs-adaptive-replanning)
9. [Sequence Diagram](#9-sequence-diagram)
10. [Universal Application](#10-universal-application)
11. [Implementation Reference](#11-implementation-reference)
12. [Failure Modes and Recovery](#12-failure-modes-and-recovery)

---

## 1. The Problem with Fixed Plans

### The Stale Plan Problem

A plan is created by analyzing the **current** screen state. But GUI
screens change with every action:

```
Screen at planning time:         Screen after step 3:
┌─────────────────────┐         ┌─────────────────────┐
│ Desktop             │         │ Notepad              │
│  - VS Code window   │   →     │  - Empty editor      │
│  - Taskbar          │         │  - File/Edit/Format  │
│  - System tray      │         │  - Title bar         │
└─────────────────────┘         └─────────────────────┘

The plan was made for the left screen.
Steps 4-10 target zones that only exist on the right screen.
```

### How Fixed Plans Fail

1. **Zone references become invalid** — the plan targets `btn_save` but
   that zone doesn't exist yet (the app hasn't opened)
2. **Context assumptions break** — the plan assumes a text field is
   focused, but a dialog stole focus
3. **Ordering assumptions break** — the plan assumes a menu is open,
   but it was dismissed by a stray click
4. **All steps become `__global__`** — the planner cannot reference
   zones that don't exist yet, so it defaults to keyboard shortcuts
   for everything, producing invisible command-only execution

### The Root Cause

> Plans are made with **current observations** but executed in a
> **changing environment**.

This is the fundamental tension in any planning-execution system.
The solution is not better planning — it's **more frequent replanning**.

---

## 2. The Rolling Horizon Model

### Concept

Instead of planning the entire task at once, plan in **segments**:

```
Plan A:  Steps for the current screen state
         → Execute → Screen changes →
Plan B:  Steps for the NEW screen state
         → Execute → Screen changes →
Plan C:  Steps for the NEWEST screen state
         → Execute → Task complete
```

Each segment:
- Is created with **fresh zone data** from the most recent screen capture
- Plans only the steps that can be executed with **currently visible zones**
- Ends at the next **major UI transition** (app opening, dialog appearing)
- Includes a `__replan__` step to signal the transition point

### Analogy: Driving a Car

You don't plan every turn from home to the office when you start the
car. You plan the next few turns based on what you can see. At each
intersection, you reassess and plan the next segment.

```
Home ──────► Turn left ──────► Traffic light ──────► Turn right ──► Office
 Plan A          │                Plan B         │        Plan C
 (3 turns)       │               (2 turns)       │       (1 turn)
             Reassess                          Reassess
             (new view)                       (new view)
```

### The Trade-off

| Approach | Plans | API Calls | Completion Rate | Resilience |
|----------|-------|-----------|-----------------|------------|
| Fixed | 1 | 1 | ~30% | Fragile |
| 2-segment | 2 | 4 | ~60% | Moderate |
| 3-segment | 3 | 7 | ~85% | Good |
| 4-segment | 4 | 10 | ~90% | Very good |
| Unlimited | N | 2N+1 | ~95% | Excellent |

---

## 3. The __replan__ Step Type

### Definition

A `__replan__` step is a **placeholder** in the plan that tells the
Director: "Stop executing, re-capture the screen, detect new zones,
and create a fresh plan for the remaining work."

```json
{
  "step_number": 4,
  "zone_id": "__replan__",
  "zone_label": "replan",
  "action_type": "replan",
  "parameters": {},
  "expected_change": "New application zones detected",
  "description": "Re-capture screen and plan remaining steps with new zones"
}
```

### How It Works

1. The **TaskPlanner** inserts `__replan__` steps after actions that
   change the screen significantly (opening an app, launching a dialog)
2. The **Director** intercepts `__replan__` before it reaches the
   StepExecutor
3. The **Director** calls `_do_recapture()` to re-capture the screen
4. The **Director** calls `_create_plan()` with fresh zones + completed
   step context
5. Execution continues from step 0 of the new plan

### When the Planner Inserts __replan__

The system prompt instructs the planner:

> "Keep plans short. Only plan steps up to the next major screen
> change, then add a `__replan__` step."

Typical insertion points:
- After opening an application (`Enter` to launch from search)
- After opening a dialog (`Ctrl+S` opens Save As)
- After switching windows (`Alt+Tab`)
- After navigating to a new page/screen

### Safety Fallback in StepExecutor

If a `__replan__` step somehow reaches the StepExecutor, it returns
success as a no-op:

```python
# In StepExecutor.execute():
if step.zone_id == "__replan__":
    return StepResult(
        step=step, success=True, action_result=None,
        events=[], error="", error_type="", timestamp=timestamp,
    )
```

---

## 4. Completed Step Tracking

### The Problem

When replanning, the planner receives the original task description
and the current zone list. Without context about what's already been
done, it may **restart the entire task from scratch**.

### The Solution

The Director maintains a `completed_descriptions` list:

```python
completed_descriptions: list[str] = []

# After each successful step:
completed_descriptions.append(step.description)

# On replan:
new_plan = self._create_plan(
    task,
    completed_steps=completed_descriptions,
)
```

### How It Appears in the Prompt

```
=== ALREADY COMPLETED (DO NOT REPEAT) ===
The following steps have ALREADY been executed successfully.
Do NOT include these in your plan:
  DONE 1. Press Windows key to open Start menu
  DONE 2. Type 'notepad' to search for the Notepad application
  DONE 3. Press Enter to launch Notepad
  DONE 4. Click in the text editor area to focus it
  DONE 5. Type the required text in the focused editor
  DONE 6. Press Ctrl+S to open the Save dialog

IMPORTANT: Plan ONLY the remaining steps needed to finish the task.
The application is already open and ready. Do NOT reopen it.
```

### Why This Prevents Restart Loops

Without completed step context, the planner sees:
- Task: "Open Notepad, type text, save"
- Zones: (Save dialog zones)
- **Planner might think:** "I need to open Notepad first" → restarts

With completed step context:
- Task: "Open Notepad, type text, save"
- Zones: (Save dialog zones)
- Completed: "Already opened Notepad, typed text, opened Save dialog"
- **Planner correctly thinks:** "Just need to fill in the filename and save"

---

## 5. The Recapture Pipeline

### Pipeline Steps

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│ 1. Capture  │────►│ 2. Encode   │────►│ 3. Send to   │
│    frame    │     │    as PNG   │     │    Tier 2    │
│ (~10ms)     │     │    base64   │     │   (25-55s)   │
└─────────────┘     └─────────────┘     └──────┬───────┘
                                               │
┌─────────────┐     ┌─────────────┐     ┌──────▼───────┐
│ 6. Return   │◄────│ 5. Update   │◄────│ 4. Parse     │
│    zone     │     │    registry │     │    JSON      │
│    count    │     │ (~1ms)      │     │    response  │
└─────────────┘     └─────────────┘     └──────────────┘
```

### Implementation

```python
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
    if resp.success and resp.zones:
        registry.replace_all(resp.zones)
        return len(resp.zones)
    if resp.success and not resp.zones:
        logger.warning(
            "Re-capture returned 0 zones (parse failure?) "
            "— keeping %d existing zones",
            registry.count,
        )
    return registry.count
```

### Failure Handling

| Failure | Action | Rationale |
|---------|--------|-----------|
| Tier 2 returns zones | Replace registry | Fresh data |
| Tier 2 returns 0 zones | Keep existing | Parse failure, stale > nothing |
| Tier 2 HTTP error | Keep existing | Transient failure |
| Tier 2 timeout | Keep existing | Server slow |

---

## 6. Plan Segment Lifecycle

### State Machine

```
                    ┌──────────┐
         ┌─────────│ PLANNING │◄────────────────────┐
         │         └────┬─────┘                     │
         │              │ plan created              │
         │              ▼                           │
         │         ┌──────────┐                     │
         │    ┌───►│EXECUTING │──── step failed ───►│ ERROR
         │    │    └──┬───┬───┘                     │ HANDLING
         │    │       │   │                         │
         │    │  step │   │ __replan__              │
         │    │  ok   │   │ step                    │
         │    │       │   │                         │
         │    │       ▼   ▼                         │
         │    │    ┌──────────┐                     │
         │    │    │RECAPTURE │ ◄── error recovery ─┘
         │    │    └────┬─────┘
         │    │         │ zones updated
         │    │         ▼
         │    │    ┌──────────┐
         │    └────│REPLANNING│
         │         └────┬─────┘
         │              │ new plan created
         │              ▼
         │         ┌──────────┐
         └────────►│ COMPLETE │
                   └──────────┘
```

### Typical 3-Segment Task Flow

```
Time ──────────────────────────────────────────────────────────────►

Segment 1 (Desktop)           Segment 2 (Notepad)         Segment 3 (Save)
┌────────────────────┐       ┌────────────────────┐      ┌───────────────────┐
│ Plan: 4 steps      │       │ Plan: 4 steps      │      │ Plan: 5 steps     │
│ 1. Win key         │       │ 1. Click editor    │      │ 1. Click Documents│
│ 2. Type "notepad"  │       │ 2. Type text       │      │ 2. Click filename │
│ 3. Enter           │       │ 3. Ctrl+S          │      │ 3. Ctrl+A         │
│ 4. __replan__      │       │ 4. __replan__      │      │ 4. Type name      │
│                    │       │                    │      │ 5. Click Save     │
│ Recapture: 50 zones│       │ Recapture: 35 zones│      │                   │
└────────────────────┘       └────────────────────┘      └───────────────────┘
      3 global                 1 visual, 2 global          3 visual, 2 global
      1 replan                 1 replan                    0 replan
```

---

## 7. Budget Management Across Replans

### Cost Per Replan

Each `__replan__` step costs:

| Component | API Calls |
|-----------|-----------|
| Recapture (Tier 2 vision) | 1 |
| New plan (text planning) | 1 |
| **Total per replan** | **2** |

### Budget Ceiling

```python
_MAX_API_CALLS: int = 30   # Hard ceiling for entire task
_MAX_REPLANS: int = 5      # Max replan attempts (adaptive + error)
```

### Budget Allocation Example

For a 30-call budget with 3 plan segments:

```
Initial plan:          1 call
Segment 1 recaptures:  3 calls (after each of 3 steps)
Replan 1:              2 calls (recapture + plan)
Segment 2 recaptures:  3 calls
Replan 2:              2 calls
Segment 3 recaptures:  1 call
────────────────────────────
Total:                 12 calls used, 18 remaining for errors/retries
```

---

## 8. Error-Based vs Adaptive Replanning

### Comparison

| Aspect | Adaptive Replan | Error Replan |
|--------|----------------|--------------|
| **Trigger** | `__replan__` step | Step failure |
| **Expected?** | Yes, planned | No, unexpected |
| **Screen state** | Known transition | Unknown state |
| **Recapture** | Always | Depends on classifier |
| **Completed steps** | Always passed | Always passed |
| **Budget count** | Shared `_MAX_REPLANS` | Shared `_MAX_REPLANS` |

### Both Use Same Infrastructure

```python
# Adaptive replan (in execute_task):
if step.zone_id == "__replan__":
    self._do_recapture()
    new_plan = self._create_plan(task, completed_steps=completed_descriptions)

# Error replan (in execute_task):
if recovery == "replan":
    new_plan = self._create_plan(task, completed_steps=completed_descriptions)
```

---

## 9. Sequence Diagram

```
User          Director       Planner        Executor      Platform
 │               │              │              │              │
 │ execute_task  │              │              │              │
 │──────────────►│              │              │              │
 │               │ plan(task)   │              │              │
 │               │─────────────►│              │              │
 │               │   TaskPlan   │              │              │
 │               │◄─────────────│              │              │
 │               │              │              │              │
 │               │ execute(step1)│              │              │
 │               │─────────────────────────────►│              │
 │               │              │              │ key_press    │
 │               │              │              │─────────────►│
 │               │              │              │   ok         │
 │               │              │              │◄─────────────│
 │               │   StepResult │              │              │
 │               │◄─────────────────────────────│              │
 │               │              │              │              │
 │               │ (delay 3s)   │              │              │
 │               │ recapture()  │              │              │
 │               │──────────────────────────────────────────►│
 │               │   50 zones   │              │              │
 │               │◄──────────────────────────────────────────│
 │               │              │              │              │
 │               │ ... steps 2,3 ...           │              │
 │               │              │              │              │
 │               │ step 4 = __replan__          │              │
 │               │ _do_recapture()             │              │
 │               │──────────────────────────────────────────►│
 │               │   35 zones   │              │              │
 │               │◄──────────────────────────────────────────│
 │               │              │              │              │
 │               │ plan(task, completed_steps)  │              │
 │               │─────────────►│              │              │
 │               │   TaskPlan B │              │              │
 │               │◄─────────────│              │              │
 │               │              │              │              │
 │               │ execute(step1 of Plan B)     │              │
 │               │─────────────────────────────►│              │
 │               │              │              │ click(zone)  │
 │               │              │              │─────────────►│
 │               │              │   ... continues ...         │
```

---

## 10. Universal Application

### Web Automation

```
Plan A: Navigate to login page
  1. Open browser
  2. Navigate to URL
  3. __replan__  (page loads, new DOM elements appear)

Plan B: Fill login form
  1. Click username field
  2. Type username
  3. Click password field
  4. Type password
  5. Click Submit
  6. __replan__  (dashboard loads)

Plan C: Perform task on dashboard
  1. Click Reports tab
  2. Click Generate button
  ...
```

### Robotic Process Automation (RPA)

```
Plan A: Open ERP application
  1. Double-click ERP icon
  2. __replan__  (ERP login screen appears)

Plan B: Login and navigate
  1. Type credentials
  2. Click Login
  3. __replan__  (main dashboard appears)

Plan C: Process invoice
  1. Click Invoices menu
  2. Click New Invoice
  3. Fill form fields
  4. Click Submit
```

### Game AI

```
Plan A: Navigate to quest giver
  1. Move character to NPC location
  2. __replan__  (dialogue options appear)

Plan B: Accept quest
  1. Click "Accept Quest"
  2. __replan__  (quest log updated, map changes)

Plan C: Complete quest objective
  1. Navigate to objective
  2. Interact with target
  3. __replan__  (quest complete dialog)
```

---

## 11. Implementation Reference

### Key Constants

```python
_MAX_API_CALLS: int = 30    # Hard budget ceiling
_MAX_REPLANS: int = 5       # Max replan attempts
_MAX_STEP_RETRIES: int = 3  # Retries per step
step_delay_seconds = 2.0    # Delay between steps (configurable)
```

### Key Files

| File | Role in Replanning |
|------|-------------------|
| `director.py` | Orchestrates replan loop, manages completed_steps |
| `task_planner.py` | Builds prompts with completed_steps context |
| `step_executor.py` | Handles __replan__ as no-op passthrough |
| `main.py` | Provides _recapture() callback |
| `settings.py` | Configures timeouts and budgets |

---

## 12. Failure Modes and Recovery

| Failure | Symptom | Recovery |
|---------|---------|----------|
| Replan returns empty plan | Plan with 0 steps | Abort with "Adaptive replan failed" |
| Recapture times out | 0 zones returned | Keep existing zones, replan with stale data |
| Planner generates duplicates | Steps repeat completed work | completed_steps context prevents this |
| Infinite replan loop | Replans keep producing same plan | _MAX_REPLANS = 5 breaks the loop |
| Budget exhaustion mid-task | API calls at ceiling | Return partial result with error |
| Parse failure on recapture | JSON unparseable | Keep existing zones, log warning |

---

## Related Documents

- [AGENT_PHILOSOPHY.md](AGENT_PHILOSOPHY.md) — Core design principles
- [TOKEN_BUDGET.md](TOKEN_BUDGET.md) — API token economics
- [DUAL_MODE_EXECUTION.md](DUAL_MODE_EXECUTION.md) — Visual vs command mode
- [DEVELOPMENT_PATTERNS.md](DEVELOPMENT_PATTERNS.md) — Code patterns
- [architecture.md](architecture.md) — System architecture
