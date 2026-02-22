# CIU Agent

**Complete Interface Usage Agent**

A visual GUI agent that treats the screen as a canvas and the cursor as a brush.

## What This Is

CIU Agent is a research prototype for autonomous GUI interaction. Instead of analyzing static screenshots at each decision point, it maintains continuous spatial awareness of the screen, tracks cursor movement in real time, and triggers actions based on zone navigation.

## How It Differs

Traditional GUI agents: snapshot → interpret → decide → act → repeat.

CIU Agent: persistent spatial map + continuous cursor tracking + selective deep analysis only when the screen changes.

This reduces API calls, increases responsiveness, and enables error detection before actions complete.

## Architecture

Five components:

- **Capture Engine** — Continuous screen recording and cursor position tracking
- **Canvas Mapper** — Builds and maintains a persistent zone map of the interface
- **Brush Controller** — Tracks cursor against zones, executes spatial actions
- **Director** — Plans tasks and orchestrates zone interactions via Claude API
- **Replay Buffer** — Records sessions for debugging and training data

Three analysis tiers:

- **Tier 0** — Frame differencing (local, every frame, negligible cost)
- **Tier 1** — Local region analysis (OCR, template matching, CPU only)
- **Tier 2** — Full canvas analysis via Claude API (on major state changes only)

See `docs/architecture.md` for the full system design.

## Requirements

- Python 3.10+
- Cross-platform: Windows, Linux, macOS
- Claude API access (Max subscription or API key)
- No GPU required — all local compute runs on CPU

## Project Status

**Current Phase:** Phase 1 — Foundation (Not Started)

See `docs/phases.md` for the build roadmap.

## Documentation

| Document | Description |
|----------|-------------|
| `CLAUDE.md` | Project config for Claude Code sessions |
| `docs/architecture.md` | Full system architecture |
| `docs/phases.md` | Build phases and deliverables |
| `docs/agents.md` | Agent and sub-agent definitions |
| `docs/conductor.md` | Conductor orchestration pattern |
| `docs/teams.md` | Team structures per phase |
| `docs/features.md` | Features, capabilities, and function index |
| `docs/skills.md` | Reusable skill definitions |

## Repository

- Remote: https://github.com/MensuraMedia/ciu_agent
- Local: `D:\projects\ciu_agent`

## License

TBD
