# CIU Agent Architecture Document

## Complete Interface Usage Agent — System Design Specification

**Version:** 0.1 (Draft)
**Date:** February 19, 2026
**Classification:** General-Purpose Research Prototype
**Inference Path:** Path D — Continuous Capture + Selective API

---

## 1. Overview

### 1.1 What is a CIU Agent

A Complete Interface Usage Agent (CIU Agent) is an autonomous software agent that interacts with graphical user interfaces by maintaining continuous spatial awareness of the screen surface, tracking cursor movement as a continuous stream, and triggering actions based on spatial zone navigation rather than discrete snapshot analysis.

### 1.2 Core Principle

The screen is a canvas. The cursor is a brush. Interactive elements are bounded zones on the canvas. Actions occur when the brush enters a zone and applies pressure (click, type, scroll). The agent maintains a persistent spatial map of the canvas and navigates it in real time, rather than re-interpreting the screen from scratch at each decision point.

### 1.3 How This Differs From Existing Approaches

Existing GUI agents (UI-TARS, CogAgent, Anthropic Computer Use, OpenAI Operator) follow a discrete loop: screenshot, interpret, decide, act, repeat. Each cycle is independent. The model has no persistent spatial memory between frames.

The CIU Agent maintains continuous awareness through three layers:

- A persistent spatial map (the Canvas) that is built once and updated incrementally
- A real-time cursor tracking stream (the Brush) that always knows where the cursor is relative to known zones
- A selective deep analysis pass that only triggers when the canvas state changes

This reduces API calls, increases responsiveness, and enables error detection before actions complete.

---

## 2. System Architecture

### 2.1 Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    DIRECTOR (Claude API)                 │
│         High-level planning + action decisions           │
│         Called selectively on state changes               │
└──────────────┬──────────────────────┬───────────────────┘
               │ task plan            │ zone queries
               ▼                      ▼
┌──────────────────────┐  ┌──────────────────────────────┐
│   CANVAS MAPPER      │  │     BRUSH CONTROLLER         │
│                      │  │                              │
│ - Zone segmentation  │◄─┤ - Cursor position stream     │
│ - Zone registry      │  │ - Zone boundary detection    │
│ - State change       │  │ - Hover/enter/exit events    │
│   detection          │  │ - Motion trajectory planning │
│ - Incremental        │  │ - Event execution            │
│   updates            │  │   (click/type/scroll)        │
└──────────┬───────────┘  └──────────────┬───────────────┘
           │                             │
           ▼                             ▼
┌──────────────────────────────────────────────────────────┐
│              CAPTURE ENGINE (Continuous)                  │
│                                                          │
│  Screen Recording ──► Frame Buffer ──► Frame Differencer │
│  Cursor Position  ──► Position Stream                    │
│  Interaction Log  ──► Replay Buffer                      │
└──────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│              OPERATING SYSTEM LAYER                       │
│  Screen capture API | Cursor position API | Input API    │
│  (cross-platform abstraction)                            │
└──────────────────────────────────────────────────────────┘
```

### 2.2 Component Summary

| Component | Purpose | Runs Where | Compute Cost |
|-----------|---------|------------|--------------|
| Capture Engine | Continuous screen recording + cursor tracking | Local CPU | Low |
| Canvas Mapper | Builds and maintains the spatial zone map | Local CPU + selective API | Medium |
| Brush Controller | Tracks cursor against zones, executes actions | Local CPU | Negligible |
| Director | High-level task planning and decision making | Claude API (remote) | Per-call |
| Replay Buffer | Records all interactions for debugging/training | Local disk | Storage only |

---

## 3. Component Specifications

### 3.1 Capture Engine

The Capture Engine provides continuous raw data streams to all other components.

**Responsibilities:**

- Capture screen frames at 15-30 fps using OS-native APIs
- Report cursor position at matching frame rate via OS cursor APIs (not vision-based)
- Feed frames into a ring buffer for the Frame Differencer
- Write full session recordings to disk for replay/debugging

**Cross-Platform Abstraction:**

| Function | Linux | Windows | macOS |
|----------|-------|---------|-------|
| Screen capture | XShm / PipeWire | DXGI Desktop Duplication | CGWindowListCreateImage |
| Cursor position | XQueryPointer | GetCursorPos | CGEventGetLocation |
| Input injection | xdotool / uinput | SendInput | CGEventPost |
| Screen recording | ffmpeg (x11grab/pipewire) | ffmpeg (gdigrab/dxgi) | ffmpeg (avfoundation) |

**Key Design Decisions:**

- Cursor position comes from the OS, not from vision. The OS always knows where the cursor is. This is faster and more accurate than trying to locate the cursor in a screenshot.
- Screen capture and cursor position are timestamped and synchronized so frames can be correlated with cursor location.
- The ring buffer holds the last N seconds of frames (configurable, default 5 seconds). Older frames are discarded unless recording is active.

**Output Streams:**

- `frame_stream`: Raw screen frames with timestamps
- `cursor_stream`: (x, y, timestamp) tuples at frame rate
- `diff_stream`: Regions of the screen that changed between consecutive frames

### 3.2 Canvas Mapper

The Canvas Mapper builds and maintains the persistent spatial map of the interface.

**Responsibilities:**

- On first frame (or major state change): perform full canvas analysis to identify all interactive zones
- On incremental changes: update only the affected regions of the map
- Maintain a Zone Registry with metadata for each detected zone
- Detect when the canvas has changed enough to require re-analysis

**Zone Definition:**

A Zone is a bounded rectangular region of the canvas that has interactive meaning.

```
Zone {
    id:          string        // unique identifier
    bounds:      Rectangle     // (x, y, width, height) in screen coordinates
    type:        ZoneType      // button, text_field, link, dropdown, checkbox,
                               // slider, menu_item, tab, scroll_area, static
    label:       string        // visible text or inferred purpose
    state:       ZoneState     // enabled, disabled, focused, hovered, pressed,
                               // checked, unchecked, expanded, collapsed
    parent_id:   string | null // containing zone (for nested elements)
    events:      Event[]       // what happens when interacted with
    confidence:  float         // 0.0-1.0, how confident the detection is
    last_seen:   timestamp     // when this zone was last confirmed present
}
```

**Analysis Tiers:**

The Canvas Mapper uses three tiers of analysis, in order of increasing cost:

| Tier | Trigger | Method | Cost |
|------|---------|--------|------|
| Tier 0: Diff Check | Every frame | OpenCV frame differencing | Negligible |
| Tier 1: Local Update | Diff exceeds threshold in a region | Lightweight segmentation on changed region only | Low (CPU) |
| Tier 2: Full Analysis | Major state change (new page, app switch) | Send full screenshot to Claude API for zone identification | API call |

**Tier 0 — Frame Differencing:**

Compare consecutive frames pixel-by-pixel (or block-by-block for efficiency). Compute the percentage of changed pixels per screen region. If below threshold (configurable, default 0.5%), no action needed. Canvas map remains valid.

**Tier 1 — Local Region Update:**

When Tier 0 detects change in a specific region, crop that region and run lightweight analysis. This can use:

- Template matching against known UI patterns (buttons, fields, etc.)
- OCR on the changed region to read new text
- Color/edge analysis to detect new boundaries

This updates only the affected zones in the registry. No API call needed.

**Tier 2 — Full Canvas Rebuild:**

When the screen changes substantially (more than 30% of pixels changed, or an application switch is detected), send the full frame to Claude API. The API response returns a complete zone inventory. The Canvas Mapper replaces its registry with the new data.

The prompt to Claude for Tier 2 analysis:

```
Analyze this screenshot and identify all interactive elements.
For each element, provide:
- Bounding box (x, y, width, height) in pixel coordinates
- Element type (button, text_field, link, dropdown, checkbox,
  slider, menu_item, tab, scroll_area)
- Visible label or text
- Current state (enabled, disabled, focused, etc.)
- Any parent-child relationships between elements

Return as structured JSON.
Screenshot dimensions: {width} x {height}
```

**State Change Detection Heuristics:**

Not every pixel change means the canvas has changed meaningfully. The Canvas Mapper uses these heuristics to classify changes:

- Cursor movement alone: Tier 0, ignore
- Tooltip appeared: Tier 1, add temporary zone
- Hover effect on known zone: Tier 1, update zone state
- Dropdown/menu opened: Tier 1, add new zones for menu items
- Page navigation / app switch: Tier 2, full rebuild
- Dialog/modal appeared: Tier 2 on the dialog region only
- Animation in progress: Wait for stability before analysis

### 3.3 Brush Controller

The Brush Controller is the real-time bridge between the cursor and the canvas map.

**Responsibilities:**

- Continuously track cursor position against the Zone Registry
- Emit spatial events (zone_enter, zone_exit, zone_hover)
- Execute motion trajectories planned by the Director
- Execute zone events (click, type, scroll) when directed
- Detect and report when the cursor is not where it's expected to be

**Spatial Event Model:**

The Brush Controller emits events based on cursor position relative to zones:

| Event | Trigger | Data |
|-------|---------|------|
| zone_enter | Cursor crosses into a zone boundary | zone_id, entry_point, timestamp |
| zone_exit | Cursor crosses out of a zone boundary | zone_id, exit_point, timestamp |
| zone_hover | Cursor has been inside a zone for > N ms | zone_id, duration, timestamp |
| zone_click | Click executed inside a zone | zone_id, click_point, button, timestamp |
| zone_type | Keystrokes sent while inside a zone | zone_id, text, timestamp |
| brush_lost | Cursor position doesn't match expected trajectory | expected_zone, actual_position |

**Motion Planning:**

Instead of teleporting the cursor to a coordinate, the Brush Controller moves it along a trajectory. This serves multiple purposes:

- Hover effects trigger naturally (some UI elements reveal information on hover)
- The motion is observable in the video stream for debugging
- Intermediate zones crossed during motion are logged
- The agent can detect errors mid-motion (cursor enters wrong zone) and correct

Trajectory types:

- `direct`: Straight line from current position to target zone center
- `safe`: Path that avoids crossing other interactive zones
- `exploratory`: Slow sweep across unknown regions to trigger hover effects and discover hidden elements

**Action Execution:**

When the Director requests an action on a specific zone:

1. Brush Controller looks up the zone in the Canvas Mapper registry
2. Plans a motion trajectory to the zone center (or specified point within zone)
3. Executes the trajectory via OS input APIs
4. Monitors cursor position during motion to verify trajectory
5. When cursor is confirmed inside the target zone, executes the action (click, type, etc.)
6. After action, monitors for canvas changes (Tier 0/1 check)
7. Reports action result back to Director

### 3.4 Director

The Director is the planning and decision-making layer. It operates at a higher level of abstraction than the other components.

**Responsibilities:**

- Accept high-level task descriptions from the user
- Decompose tasks into sequences of zone interactions
- Query the Canvas Mapper for available zones and their states
- Issue action commands to the Brush Controller
- Handle errors and re-plan when actions fail
- Maintain task context across multiple steps

**Operating Model:**

The Director does not process raw pixels or video. It works entirely with structured data:

- The Zone Registry (from Canvas Mapper): what zones exist and their states
- Spatial events (from Brush Controller): what happened during cursor movement
- Action results: did the last action succeed or fail

This is a critical design point. By abstracting the visual complexity into structured zone data, the Director's reasoning problem becomes much simpler. It's working with a list of named, typed, stateable interactive elements — not trying to interpret raw screenshots.

**Planning Format:**

The Director produces plans in this format:

```
Task: "Open the document and save it as PDF"

Plan:
  Step 1: Navigate to zone "File" (type: menu_item) → click
  Step 2: Wait for canvas change (menu dropdown expected)
  Step 3: Navigate to zone "Save As" (type: menu_item) → click
  Step 4: Wait for canvas change (dialog expected)
  Step 5: Navigate to zone "Format" (type: dropdown) → click
  Step 6: Navigate to zone "PDF" (type: menu_item) → click
  Step 7: Navigate to zone "Save" (type: button) → click

Current step: 1
Status: executing
```

**Error Handling:**

| Error Type | Detection | Recovery |
|------------|-----------|----------|
| Zone not found | Director requests zone that doesn't exist in registry | Trigger Tier 2 re-analysis, then re-plan |
| Wrong zone clicked | Canvas changes don't match expected result | Undo (Ctrl+Z) or navigate back, re-plan |
| Zone state unexpected | Zone is disabled when expected enabled | Wait, retry, or find alternative path |
| Brush lost | Cursor not in expected position | Recalibrate: move cursor to known position, restart step |
| Timeout | Expected canvas change doesn't occur within threshold | Re-execute action, then escalate to re-plan |
| Task impossible | Required functionality not found on canvas | Report to user with explanation |

**API Usage Pattern:**

The Director calls Claude API in these situations:

- Task decomposition: once per new task
- Re-planning after errors: as needed
- Ambiguous zone identification: when Tier 1 analysis is insufficient
- Complex decision points: when the next step depends on interpreting on-screen content

Estimated API calls per typical task: 3-8 (compared to 15-50 for snapshot-per-step agents).

### 3.5 Replay Buffer

**Responsibilities:**

- Record all screen frames, cursor positions, and agent actions to disk
- Enable session replay for debugging
- Provide training data for future model fine-tuning
- Log all spatial events and Director decisions with timestamps

**Storage Format:**

```
session_YYYYMMDD_HHMMSS/
├── frames/              # PNG frames at capture rate
│   ├── 000001.png
│   ├── 000002.png
│   └── ...
├── cursor.jsonl         # cursor positions, one per line
├── zones.jsonl          # zone registry snapshots
├── events.jsonl         # spatial events from Brush Controller
├── actions.jsonl        # Director actions and decisions
├── session.mp4          # compressed video of full session
└── metadata.json        # session config, timestamps, task description
```

---

## 4. Data Flow

### 4.1 Startup Sequence

1. Capture Engine starts screen recording and cursor tracking
2. Canvas Mapper receives first frame, performs Tier 2 full analysis (API call)
3. Zone Registry is populated with all detected interactive elements
4. Brush Controller begins tracking cursor position against Zone Registry
5. Director receives task from user, produces initial plan
6. System enters main loop

### 4.2 Main Loop (Continuous)

```
Every frame (15-30 fps):
  1. Capture Engine delivers frame + cursor position
  2. Canvas Mapper runs Tier 0 diff check
     - No change → continue
     - Change detected → run Tier 1 or Tier 2 as appropriate
     - Update Zone Registry if needed
  3. Brush Controller updates cursor-to-zone mapping
     - Emit spatial events (enter, exit, hover)
  4. If Director has pending action:
     - Brush Controller executes next motion step
     - If action complete: report result to Director
  5. If Director needs to decide next step:
     - Director queries Zone Registry + event history
     - Director produces next action (or calls API for planning)
  6. Replay Buffer logs everything
```

### 4.3 Tier Escalation Flow

```
Frame received
    │
    ▼
Tier 0: Diff check
    │
    ├── < 0.5% pixels changed → No action
    │
    ├── 0.5% - 30% changed in localized region → Tier 1
    │       │
    │       └── Run local segmentation on changed region
    │           Update affected zones in registry
    │
    └── > 30% changed OR app switch detected → Tier 2
            │
            └── Send full frame to Claude API
                Replace entire Zone Registry
                Director re-evaluates current plan
```

---

## 5. Cross-Platform Strategy

### 5.1 Abstraction Layer

All OS-specific functionality is isolated behind a Platform Interface:

```
PlatformInterface {
    capture_frame()    → Frame
    get_cursor_pos()   → (x, y)
    move_cursor(x, y)  → void
    click(x, y, btn)   → void
    type_text(text)     → void
    key_press(key)      → void
    scroll(x, y, amt)   → void
    get_screen_size()   → (width, height)
    get_active_window() → WindowInfo
    list_windows()      → WindowInfo[]
}
```

### 5.2 Platform Implementations

Each platform provides a concrete implementation:

| Method | Linux | Windows | macOS |
|--------|-------|---------|-------|
| capture_frame | mss (Python) or XShm | mss or DXGI | mss or CGImage |
| get_cursor_pos | Xlib | ctypes → GetCursorPos | Quartz |
| move_cursor | xdotool / pynput | ctypes → SetCursorPos | Quartz |
| click | xdotool / pynput | ctypes → SendInput | Quartz |
| type_text | xdotool / pynput | ctypes → SendInput | Quartz |
| key_press | xdotool / pynput | ctypes → SendInput | Quartz |
| scroll | xdotool / pynput | ctypes → SendInput | Quartz |

Python's `pynput` library covers most of these cross-platform. Platform-specific implementations are used only where pynput is insufficient (primarily screen capture performance).

### 5.3 Resolution and Scaling

The Canvas Mapper operates in logical coordinates (what the OS reports) not physical pixels. DPI scaling is handled by the Platform Interface. All zone coordinates are in logical space.

---

## 6. Dependencies

### 6.1 Required (all platforms)

| Dependency | Purpose | Install |
|------------|---------|---------|
| Python 3.10+ | Runtime | System |
| OpenCV (cv2) | Frame differencing, basic image analysis | pip |
| mss | Cross-platform screen capture | pip |
| pynput | Cross-platform input control | pip |
| numpy | Array operations for frame processing | pip |
| Pillow | Image handling | pip |
| httpx or requests | Claude API calls | pip |

### 6.2 Optional

| Dependency | Purpose | When Needed |
|------------|---------|-------------|
| ffmpeg | Session video recording | Replay buffer |
| pytesseract | Local OCR for Tier 1 text reading | Reduce API calls |
| onnxruntime | Run SAM or other segmentation models locally | Advanced Tier 1 |

### 6.3 API Requirements

| Service | Purpose | Access |
|---------|---------|--------|
| Claude API (Anthropic) | Director planning + Tier 2 canvas analysis | Claude Max subscription / API key |

---

## 7. File Structure

```
ciu_agent/
├── core/
│   ├── capture_engine.py      # Screen recording + cursor tracking
│   ├── canvas_mapper.py       # Zone segmentation + registry
│   ├── brush_controller.py    # Cursor tracking + action execution
│   ├── director.py            # Task planning + API calls
│   └── replay_buffer.py       # Session recording
├── platform/
│   ├── interface.py           # Abstract platform interface
│   ├── linux.py               # Linux implementation
│   ├── windows.py             # Windows implementation
│   └── macos.py               # macOS implementation
├── models/
│   ├── zone.py                # Zone data model
│   ├── events.py              # Spatial event definitions
│   └── actions.py             # Action definitions
├── config/
│   └── settings.py            # Configuration defaults
├── sessions/                  # Replay data (gitignored)
├── tests/
│   ├── test_capture.py
│   ├── test_canvas.py
│   ├── test_brush.py
│   └── test_director.py
├── requirements.txt
├── setup.py
└── README.md
```

---

## 8. Build Phases

### Phase 1: Foundation (Capture Engine + Platform Layer)

Goal: Continuous screen capture and cursor tracking working cross-platform.

Deliverables:

- Platform abstraction layer with at least one implementation
- Screen capture at 15+ fps
- Cursor position streaming
- Frame differencing (Tier 0)
- Basic session recording

Validation: Can record a 60-second session and replay it with synchronized cursor overlay.

### Phase 2: Canvas (Canvas Mapper)

Goal: Build and maintain a persistent zone map of the screen.

Deliverables:

- Tier 2 full analysis via Claude API
- Zone Registry data structure
- Tier 0 change detection integrated with Capture Engine
- Tier 1 local updates for common patterns (text changes, hover effects)

Validation: Can map a desktop with multiple windows open. Zone map persists correctly when cursor moves. Updates correctly when a window is opened or closed.

### Phase 3: Brush (Brush Controller)

Goal: Real-time cursor-to-zone tracking with spatial events.

Deliverables:

- Continuous zone tracking (enter/exit/hover events)
- Motion trajectory planning (direct and safe paths)
- Action execution (click, type, scroll) with zone verification
- Brush-lost detection

Validation: Can move cursor to a named zone and click it. Emits correct spatial events during motion. Detects when cursor enters wrong zone.

### Phase 4: Director (Planning Layer)

Goal: Accept tasks and execute them through zone interactions.

Deliverables:

- Task decomposition via Claude API
- Step-by-step execution through Brush Controller
- Error detection and re-planning
- Basic task completion verification

Validation: Can execute a multi-step task (e.g., "open Notepad and type hello world") end to end.

### Phase 5: Integration and Hardening

Goal: Full system operating reliably.

Deliverables:

- All components integrated
- Cross-platform testing
- Error recovery for common failure modes
- Performance optimization (frame rate, API call minimization)
- Replay viewer for debugging

---

## 9. Open Questions and Risks

### 9.1 Open Questions

- What is the minimum acceptable confidence threshold for zone detection before the agent should act?
- Should the Brush Controller simulate human-like mouse movement (curves, acceleration) or use direct paths?
- How should the system handle applications that use custom-rendered UI (games, Electron apps with non-standard widgets)?
- Should the Replay Buffer record raw frames or compressed video? Tradeoff between disk usage and frame-accurate replay.

### 9.2 Known Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Claude API latency (2-5s per call) | Slow Tier 2 rebuilds, slow Director decisions | Minimize API calls via effective Tier 0/1 filtering |
| Zone misidentification | Wrong element clicked, task derailed | Confidence thresholds + Brush Controller verification |
| DPI/scaling inconsistencies across platforms | Coordinates off by scaling factor | Platform layer normalizes all coordinates to logical space |
| High frame rate capture on Intel UHD | CPU load from continuous capture | Adaptive frame rate: high during action, low during idle |
| API cost accumulation | Budget concerns for heavy usage | Tier escalation design already minimizes calls |

---

## 10. Future Extensions (Not In Scope For Prototype)

- Local vision model (UI-TARS-1.5-7B) replacing Claude API for Tier 2 when GPU hardware is available
- Multi-monitor support
- Zone learning: the system remembers zone layouts for frequently used applications and skips Tier 2 on re-encounter
- Voice control integration
- Task recording: watch a human perform a task, learn the zone sequence, replay it
- Accessibility tree integration as supplementary data source (where available)
