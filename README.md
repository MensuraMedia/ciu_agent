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

## Agents

The project is built using a conductor pattern with specialized agents. Each agent owns a domain and operates within its own context window. The Conductor orchestrates across domains.

| Agent | Role | Model Tier | Owns |
|-------|------|------------|------|
| **Conductor** | Orchestration — decomposes phases into tasks, assigns work, tracks progress, resolves conflicts | — | Task board, phase workflow |
| **Architect** | System design — defines component interfaces, resolves cross-component conflicts, reviews structural changes | Opus | Architecture docs, interfaces, data models |
| **Platform Engineer** | Cross-platform abstraction — implements OS-specific capture, input, and cursor functions | Sonnet | `ciu_agent/platform/` |
| **Capture Specialist** | Screen recording — continuous capture, frame ring buffer, Tier 0 differencing, session recording | Sonnet | `ciu_agent/core/capture_engine.py` |
| **Canvas Specialist** | Zone segmentation — builds and maintains the spatial zone map, Tier 1/2 analysis, zone registry | Opus | `ciu_agent/core/canvas_mapper.py` |
| **Brush Specialist** | Cursor tracking — continuous zone mapping, spatial events, motion trajectories, action execution | Sonnet | `ciu_agent/core/brush_controller.py` |
| **Director Specialist** | Task planning — natural language decomposition, step execution, error recovery, task verification | Opus | `ciu_agent/core/director.py` |
| **Token Warden** | Cost enforcement — tracks per-agent token budgets, flags violations, enforces compaction, produces session reports | Sonnet | Token logs and violation records |
| **Test Engineer** | Testing — unit tests, integration tests, mock builders, cross-platform validation | Sonnet | `tests/` |
| **Documentation** | Docs — keeps architecture docs, README, docstrings, and changelog current | Sonnet | `docs/`, README |

Each agent can spawn sub-agents for focused tasks within its domain. See `docs/agents.md` for full sub-agent definitions and `docs/teams.md` for phase-specific team configurations.

## Token Operations

All sessions follow a token operations policy to minimize API costs and context waste. Key principles:

- **Progressive disclosure** — Load docs only when the current task needs them, not all at once
- **Tiered analysis** — Use the cheapest effective method for every task (local tools before API calls)
- **Subagent hygiene** — Delegate large file reads and verbose commands to subagents to keep the main context clean
- **Budget enforcement** — The Token Warden monitors per-agent budgets and triggers compaction at 70% capacity
- **MCP integration** — GitHub, Context7, Sequential Thinking, and Memory MCPs provide structured access to tools and knowledge without bloating the context window

See `docs/token_ops.md` for the full policy and `docs/token_savings.md` for procedures.

## Requirements

- Python 3.10+
- Cross-platform: Windows, Linux, macOS
- Claude API access (Max subscription or API key)
- No GPU required — all local compute runs on CPU

## Installation

```bash
git clone https://github.com/MensuraMedia/ciu_agent.git
cd ciu_agent
pip install -r requirements.txt
```

## Usage

### Run a task

```bash
python -m ciu_agent.main --task "Open Notepad and type hello world" --api-key sk-ant-...
```

Or set the API key as an environment variable:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python -m ciu_agent.main --task "Click the Save button"
```

### Options

- `--task` / `-t`: Task to execute (required)
- `--api-key` / `-k`: Anthropic API key (or set `ANTHROPIC_API_KEY`)
- `--verbose` / `-v`: Enable debug logging

### Replay a session

```bash
python -m ciu_agent.replay_viewer --session sessions/session_20260222_143000 --speed 2.0
```

### Run tests

```bash
python -m pytest tests/ -v
```

## API Overview

| Class | Module | Description |
|-------|--------|-------------|
| `CIUAgent` | `ciu_agent.main` | Main agent entry point |
| `Director` | `ciu_agent.core.director` | Task orchestrator |
| `BrushController` | `ciu_agent.core.brush_controller` | Cursor control |
| `CanvasMapper` | `ciu_agent.core.canvas_mapper` | Zone map |
| `CaptureEngine` | `ciu_agent.core.capture_engine` | Screen capture |
| `ReplayBuffer` | `ciu_agent.core.replay_buffer` | Session recording |

## Project Status

**Current Phase:** All 5 phases complete (v0.1.0)

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
| `docs/permissions.md` | Permissions policy for Claude Code sessions |
| `docs/token_ops.md` | Token operations policy and task-to-tool routing |
| `docs/token_savings.md` | Token-saving procedures and anti-patterns |
| `docs/token_warden_agent.md` | Token Warden agent specification |

## Repository

- Remote: https://github.com/MensuraMedia/ciu_agent
- Local: `D:\projects\ciu_agent`

## License

TBD
