# CIU Agent — Skills

## What Skills Are

Skills are reusable instruction sets that teach agents how to perform specific categories of work. They are not step-by-step scripts. They define approach, constraints, and quality criteria. Agents read a skill when they encounter work in that category.

Skills live in `skills/` at the project root. Each skill is a directory containing a `SKILL.md` file.

## Available Skills

### Git (Commit and Push)

**Location:** `skills/git/SKILL.md`
**Used by:** All agents (via Conductor)
**Trigger:** After completing a task, after phase milestones, on explicit request.

Handles: staging, conventional commit messages, pushing to remote, branch management, error recovery for push conflicts.

### Python Module Creation

**Location:** `skills/python-module/SKILL.md`
**Used by:** All implementation agents
**Trigger:** When creating a new Python file that will be part of the `ciu_agent` package.

Defines: file header format, import ordering, type hint requirements, docstring format, test file creation.

```
skills/python-module/SKILL.md contents:

# Skill: Python Module Creation

When creating a new Python module in the ciu_agent package:

1. Add module docstring at top explaining purpose
2. Order imports: stdlib, third-party, local (separated by blank lines)
3. All public functions and classes require:
   - Type hints on all parameters and return types
   - Google-style docstring with Args, Returns, Raises sections
4. Use dataclass for structured data, not plain dicts
5. No global mutable state
6. Create corresponding test file in tests/ with same name prefixed by test_
7. Add the module to __init__.py if it should be publicly importable
```

### API Integration

**Location:** `skills/api-integration/SKILL.md`
**Used by:** Canvas Specialist (Tier 2), Director Specialist
**Trigger:** When writing code that calls the Claude API.

Defines: API call structure, error handling for API failures, response parsing, rate limiting, cost tracking.

```
skills/api-integration/SKILL.md contents:

# Skill: Claude API Integration

When making Claude API calls:

1. Use httpx with async support for non-blocking calls
2. Always set a timeout (default: 30 seconds for vision, 15 for text)
3. Handle these error cases:
   - 429 rate limit: exponential backoff, max 3 retries
   - 500/502/503: retry once after 5 seconds
   - Timeout: retry once, then report failure
   - Malformed response: log the raw response, return error
4. Parse structured responses (JSON) with validation
5. Log every API call: timestamp, prompt length, response length, latency
6. Track cumulative token usage per session for cost awareness
7. Never include sensitive data (credentials, personal info) in API prompts
```

### Cross-Platform Code

**Location:** `skills/cross-platform/SKILL.md`
**Used by:** Platform Engineer, Capture Specialist
**Trigger:** When writing code that interacts with OS-specific functionality.

Defines: abstraction layer usage, platform detection, fallback behavior, testing approach.

```
skills/cross-platform/SKILL.md contents:

# Skill: Cross-Platform Code

When writing OS-specific code:

1. Never put OS-specific code in ciu_agent/core/
2. All OS interaction goes through ciu_agent/platform/interface.py
3. Use platform.system() for runtime detection: "Windows", "Linux", "Darwin"
4. Each platform implementation is a separate file in ciu_agent/platform/
5. If a platform feature is unavailable, raise NotImplementedError with a clear message
6. Test with mock platform interfaces, not real OS calls
7. Document any platform-specific limitations in the implementation file
```

### Testing

**Location:** `skills/testing/SKILL.md`
**Used by:** Test Engineer, all agents when writing tests
**Trigger:** When creating or updating test files.

Defines: test naming conventions, fixture usage, mock strategies, assertion style.

```
skills/testing/SKILL.md contents:

# Skill: Testing

When writing tests:

1. Test files mirror source: ciu_agent/core/capture_engine.py → tests/test_capture_engine.py
2. Test function names: test_<what>_<condition>_<expected>
   Example: test_frame_diff_no_change_returns_zero
3. Use pytest fixtures for reusable setup
4. Mock external dependencies (OS calls, API calls, file system)
5. One assertion per test when practical
6. Group related tests in classes: class TestFrameDifferencer
7. Mark slow tests with @pytest.mark.slow
8. Mark platform-specific tests with @pytest.mark.platform("windows")
9. Always test error cases, not just happy paths
```

## Adding New Skills

When a pattern emerges that multiple agents need to follow:

1. Create a new directory under `skills/`
2. Write a `SKILL.md` defining the approach
3. Reference it in this index file
4. Update `CLAUDE.md` if the skill applies globally
