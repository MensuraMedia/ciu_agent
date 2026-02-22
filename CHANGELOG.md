# Changelog

All notable changes to CIU Agent (Complete Interface Usage Agent) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-02-22

### Added

#### Phase 1 — Foundation
- Platform abstraction layer (`PlatformInterface` ABC) with Windows (full), Linux/macOS (stubs)
- `CaptureEngine` for continuous screen capture with ring buffer and frame differencing (Tier 0)
- `ReplayBuffer` for session recording to disk (frames, cursor positions, events, actions, metadata)
- Data models: `Zone`, `SpatialEvent`, `Action`, `ActionType`, `ActionStatus`, `Trajectory`
- `Settings` dataclass with all tunable parameters
- `requirements.txt` with all project dependencies

#### Phase 2 — Canvas
- `CanvasMapper` orchestrator wiring all analysis tiers and the zone registry
- `ZoneRegistry` with thread-safe CRUD, spatial queries, and staleness expiry
- `StateClassifier` for heuristic routing (Tier 0/1/2) based on frame diffs
- `Tier1Analyzer` for local region analysis using OpenCV (text detection, hover states, tooltips)
- `Tier2Analyzer` for full canvas analysis via Claude API (vision endpoint)

#### Phase 3 — Brush
- `ZoneTracker` for continuous cursor-to-zone tracking with ZONE_ENTER/EXIT/HOVER events
- `MotionPlanner` for trajectory generation (direct, safe with obstacle avoidance, exploratory sweep)
- `ActionExecutor` for input action execution (click, double_click, type_text, key_press, scroll, move) with zone verification
- `BrushController` orchestrator wiring tracker, planner, and executor together

#### Phase 4 — Director
- `TaskPlanner` for Claude API task decomposition (natural language to zone interaction steps)
- `StepExecutor` for single-step execution via `BrushController`
- `ErrorClassifier` for error classification with recovery strategies (retry, replan, reanalyze, skip, abort)
- `Director` as the top-level orchestrator (plan, execute, handle errors, replan)
- `TaskStep` and `TaskPlan` shared models

#### Phase 5 — Integration and Hardening
- Main entry point (`main.py`) wiring all components end-to-end
- `CIUAgent` class with `run_task()`, `startup()`, and `shutdown()` lifecycle methods
- CLI interface with `--task`, `--api-key`, and `--verbose` options
- `ReplayViewer` for session playback and debugging
- End-to-end integration tests (858+ unit tests across all modules, all passing)
- README with setup instructions, usage guide, and examples

[Unreleased]: https://github.com/MensuraMedia/ciu_agent/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MensuraMedia/ciu_agent/releases/tag/v0.1.0
