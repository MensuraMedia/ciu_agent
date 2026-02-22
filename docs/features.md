# CIU Agent — Features and Capabilities

## Core Capabilities

### 1. Continuous Screen Awareness

The agent maintains a live spatial map of the screen at all times. Unlike snapshot-based agents that re-interpret the screen from scratch at each decision point, the CIU Agent builds a persistent map and updates it incrementally.

**Functions:**

- `capture_frame()` — Grab the current screen state
- `get_cursor_position()` — Get cursor coordinates via OS API (not vision)
- `compute_frame_diff(frame_a, frame_b)` — Identify changed regions between frames
- `classify_change(diff_result)` — Determine if the change requires Tier 1 or Tier 2 analysis

### 2. Zone Segmentation and Registry

Every interactive element on screen is identified and stored as a Zone with metadata: type, label, state, boundaries, confidence score. The Zone Registry is the single source of truth for what's on screen.

**Functions:**

- `analyze_full_canvas(frame)` — Tier 2: Send frame to Claude API, return full zone inventory
- `analyze_region(frame, region)` — Tier 1: Run local analysis on a changed region
- `register_zone(zone)` — Add a new zone to the registry
- `update_zone(zone_id, changes)` — Update an existing zone's properties
- `remove_zone(zone_id)` — Remove a zone that no longer exists
- `find_zone_by_label(label)` — Look up a zone by its visible text
- `find_zone_by_type(zone_type)` — Find all zones of a given type (buttons, fields, etc.)
- `find_zone_at_point(x, y)` — Return the zone containing a given coordinate
- `get_all_zones()` — Return the full registry

### 3. Spatial Cursor Tracking

The cursor is tracked continuously against the zone map. Spatial events are emitted when the cursor enters, exits, or hovers within zones.

**Functions:**

- `track_cursor(position, zone_registry)` — Map cursor position to current zone
- `emit_event(event_type, zone_id, data)` — Fire a spatial event
- `is_cursor_in_zone(zone_id)` — Check if cursor is currently inside a zone
- `get_current_zone()` — Return the zone the cursor is currently in (or null)

### 4. Motion Trajectory Planning

Instead of teleporting the cursor, the agent plans motion paths. Trajectories can avoid non-target zones and can be monitored during execution.

**Functions:**

- `plan_direct_path(from_pos, to_zone)` — Straight line to target zone center
- `plan_safe_path(from_pos, to_zone, avoid_zones)` — Path that avoids crossing specified zones
- `plan_exploratory_sweep(region)` — Slow sweep to discover hidden or hover-revealed elements
- `execute_trajectory(trajectory)` — Move the cursor along the planned path
- `verify_arrival(target_zone)` — Confirm cursor is inside the target zone

### 5. Action Execution

The agent performs mouse and keyboard actions within targeted zones.

**Functions:**

- `click_zone(zone_id, button="left")` — Move to zone and click
- `double_click_zone(zone_id)` — Move to zone and double click
- `type_in_zone(zone_id, text)` — Move to zone, click to focus, type text
- `scroll_in_zone(zone_id, direction, amount)` — Move to zone and scroll
- `key_press(key)` — Press a keyboard key (for shortcuts, hotkeys)
- `drag_from_to(zone_a, zone_b)` — Click-drag from one zone to another

### 6. Task Planning and Decomposition

Natural language tasks are decomposed into sequences of zone interactions.

**Functions:**

- `decompose_task(description, zone_registry)` — Convert task description into step sequence
- `get_next_step(plan, current_state)` — Return the next action to take
- `replan(plan, error, zone_registry)` — Revise the plan after an error
- `verify_task_complete(plan, zone_registry)` — Check if the task goal has been achieved

### 7. Error Detection and Recovery

The agent detects when things go wrong and attempts to recover.

**Functions:**

- `detect_error(expected_state, actual_state)` — Compare expected vs actual canvas state
- `classify_error(error)` — Categorize the error type
- `attempt_recovery(error_type, context)` — Execute recovery strategy for the error type
- `escalate_to_user(error, context)` — Report unrecoverable error to the user

### 8. Session Recording and Replay

All interactions are recorded for debugging and training data collection.

**Functions:**

- `start_recording(session_id)` — Begin capturing frames, cursor, events, and actions
- `stop_recording()` — End capture and finalize session files
- `save_session(path)` — Write session data to disk
- `load_session(path)` — Load a recorded session for replay
- `replay_session(session, speed)` — Play back a recorded session

## Feature Matrix

| Feature | Phase | Local/API | CPU Cost | API Cost |
|---------|-------|-----------|----------|----------|
| Screen capture | 1 | Local | Low | None |
| Cursor tracking | 1 | Local | Negligible | None |
| Frame differencing | 1 | Local | Low | None |
| Session recording | 1 | Local | Storage | None |
| Zone segmentation (Tier 1) | 2 | Local | Medium | None |
| Zone segmentation (Tier 2) | 2 | API | Low | Per call |
| Zone registry | 2 | Local | Negligible | None |
| Spatial events | 3 | Local | Negligible | None |
| Motion planning | 3 | Local | Low | None |
| Action execution | 3 | Local | Low | None |
| Task decomposition | 4 | API | Low | Per task |
| Error recovery | 4 | Mixed | Low | Sometimes |
| Replay viewer | 5 | Local | Low | None |

## Limitations (Known)

- No multi-monitor support in prototype
- No accessibility tree integration (pure vision only)
- Custom-rendered UIs (games, canvas-based apps) may have poor zone detection
- Intel UHD hardware limits local model inference — API dependency for Tier 2
- API latency (2-5s) makes Tier 2 rebuilds noticeable
- Zone confidence below threshold requires user confirmation
