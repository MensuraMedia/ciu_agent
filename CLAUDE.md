# CIU Agent

Complete Interface Usage Agent — a visual GUI agent that treats the screen as a canvas and the cursor as a brush.

## Project

- Repo: `https://github.com/MensuraMedia/ciu_agent`
- Local: `D:\projects\ciu_agent`
- Language: Python 3.10+
- Target: Cross-platform (Windows, Linux, macOS)
- Inference: Path D — continuous screen capture with selective Claude API calls

## Architecture

See `docs/architecture.md` for full system design.

Five components: Capture Engine, Canvas Mapper, Brush Controller, Director, Replay Buffer.
Three analysis tiers: Tier 0 (frame diff, local), Tier 1 (region update, local), Tier 2 (full analysis, API).

## Commands

```bash
# Run the agent
python -m ciu_agent.main

# Run tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_capture.py -v

# Type checking
python -m mypy ciu_agent/ --strict

# Lint
python -m ruff check ciu_agent/

# Format
python -m ruff format ciu_agent/

# Install dependencies
pip install -r requirements.txt
```

## Code Style

- Python 3.10+ with type hints on all public functions
- Use `dataclass` or `TypedDict` for structured data, not plain dicts
- Prefer composition over inheritance
- Abstract base classes for platform interfaces
- No global state. Pass dependencies explicitly.
- Docstrings on all public classes and functions (Google style)
- Max line length: 100 characters

## File Structure

```
ciu_agent/
├── core/           # Main components (capture, canvas, brush, director, replay)
├── platform/       # OS-specific implementations (linux, windows, macos)
├── models/         # Data models (zone, events, actions)
├── config/         # Settings and defaults
├── skills/         # Reusable Claude Code skills
├── tests/          # Test files mirror source structure
├── docs/           # Architecture, specs, agent definitions
├── sessions/       # Replay data (gitignored)
└── .claude/        # Claude Code commands and agents
```

## Git Workflow

See `skills/git/SKILL.md` for the full git skill.

- Use conventional commits: `type(scope): description`
- Scopes: `capture`, `canvas`, `brush`, `director`, `platform`, `config`, `docs`
- Always check `git status` before staging
- Never commit `.env`, API keys, or session recordings
- Push to `https://github.com/MensuraMedia/ciu_agent`

## Build Phases

Current phase: **Phase 1 — Foundation**

1. Foundation (Capture Engine + Platform Layer)
2. Canvas (Canvas Mapper + Zone Registry)
3. Brush (Brush Controller + Spatial Events)
4. Director (Planning Layer + API Integration)
5. Integration and Hardening

See `docs/phases.md` for detailed phase specs.

## Important Notes

- Never name any folder or file `claude` within the project tree
- All scripts must be Debian-compatible shell files when greater than 3 lines
- Script files follow naming convention: `s001_`, `s002_`, etc.
- Pause after producing code for review before proceeding
- The target hardware has Intel UHD Graphics (2GB shared VRAM). All local compute must run on CPU.
- Cross-platform abstractions go in `ciu_agent/platform/`. Never put OS-specific code in `core/`.
