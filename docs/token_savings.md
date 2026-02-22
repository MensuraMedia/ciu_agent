# CIU Agent — Token Savings

## Purpose

This document defines mandatory token-saving procedures for all Claude Code sessions working on the CIU Agent project. Every agent, sub-agent, and team member must follow these rules. Context is the bottleneck, not intelligence.

## Core Principle

Every token must justify its presence in the context window. If it doesn't contribute to the current task, it shouldn't be there.

---

## Session Lifecycle

### Starting a Session

1. Read `CLAUDE.md` (loaded automatically — keep it lean)
2. Read only the docs relevant to the current task. Do not load all docs at once.
3. Check `docs/taskboard.json` for current task assignment
4. Begin work immediately

### During a Session

- Run `/cost` periodically to monitor token usage
- Compact at 70% context capacity, not at 95% when auto-compact triggers
- Use custom compact instructions to preserve what matters:

```
/compact Preserve: current task ID, modified file paths, test results, and error messages. Discard: file contents already committed, exploration attempts that failed, verbose command output.
```

### Between Tasks

- Run `/clear` when switching to an unrelated task
- Before clearing, commit current work via git skill
- Write a one-paragraph status note to `docs/session_notes.md` so the next session can resume without re-reading everything

### Ending a Session

- Commit all work
- Run `/cost` and log the session cost to `docs/token_log.md`
- Update `docs/taskboard.json` with current state

---

## CLAUDE.md Management

The root `CLAUDE.md` is loaded into every session. Its size directly affects every single message cost.

**Rules:**

- Keep `CLAUDE.md` under 500 lines
- Keep `CLAUDE.md` under 5,000 tokens
- Include only universally applicable information
- Point to docs for detail, never inline full specs
- Never use `@file` references in CLAUDE.md (embeds the entire file into every message)

**What belongs in CLAUDE.md:**

- Project name and one-line description
- Tech stack summary
- Common commands (test, lint, build)
- Code style rules (short list)
- File structure overview
- Current build phase
- Critical gotchas (things Claude gets wrong)

**What does NOT belong in CLAUDE.md:**

- Full architecture spec (point to `docs/architecture.md`)
- Agent definitions (point to `docs/agents.md`)
- Detailed phase specs (point to `docs/phases.md`)
- Feature descriptions (point to `docs/features.md`)
- Long examples or tutorials

---

## Progressive Disclosure

Load information only when needed. Never front-load all project knowledge.

**Pattern:**

```
CLAUDE.md (always loaded, ~500 lines)
    │
    ├── "For architecture details, see docs/architecture.md"
    ├── "For current tasks, see docs/taskboard.json"
    └── "For agent roles, see docs/agents.md"
```

Agents read these files only when their task requires it. The Conductor reads `phases.md` and `taskboard.json`. The Platform Engineer reads `architecture.md` section 5 only. The Test Engineer reads `docs/skills.md` testing section only.

---

## Subagent Token Hygiene

Subagents run in separate context windows. Use them to keep the main session clean.

**When to use subagents:**

- Reading large files (let the subagent read, summarize, and report back)
- Researching the codebase (subagent explores, returns findings as a short summary)
- Running verbose commands (test suites, linters with many warnings)
- Exploring options (subagent investigates three approaches, recommends one)

**Subagent rules:**

- Subagent prompt should be specific and bounded
- Subagent should return a summary, not raw output
- Never have the main session re-read what a subagent already processed

**Example:**

```
Use a subagent to read all files in ciu_agent/platform/ and report:
1. Which PlatformInterface methods are implemented per platform
2. Which methods are missing or raise NotImplementedError
3. Any inconsistencies between implementations
Return a table, not the file contents.
```

This keeps the main session's context clean while still getting the information needed.

---

## Command Output Management

Verbose command output is one of the biggest token consumers.

**Rules:**

- Truncate test output. Pipe through `tail -30` unless full output is needed.
- Filter for relevant lines. Use `grep -i "error\|warning\|fail"` on build output.
- Limit directory listings. Use `tree -L 2` not `tree`.
- Redirect verbose output to files. Read the file only if errors occur.

**Patterns:**

```bash
# Bad: dumps entire test output into context
pytest tests/ -v

# Good: only show failures
pytest tests/ -v 2>&1 | tail -30

# Bad: full directory tree
tree

# Good: two levels deep
tree -L 2

# Bad: full git log
git log

# Good: compact recent history
git log --oneline -10

# Bad: full file content for large files
cat ciu_agent/core/canvas_mapper.py

# Good: specific section only
sed -n '50,80p' ciu_agent/core/canvas_mapper.py
```

---

## File Reading Strategy

**Rules:**

- Read only the files needed for the current task
- Read specific line ranges when possible, not entire files
- Use grep to find relevant sections before reading
- Never re-read a file that hasn't changed since last read
- For files over 200 lines, read by section

**Scratchpad pattern:**

When a task requires reading multiple files to gather information:

1. Read each file once
2. Write the relevant findings to a temporary scratchpad file (`/tmp/scratchpad.md`)
3. Reference the scratchpad for the rest of the task
4. Delete the scratchpad when done

This avoids re-reading source files multiple times during a single task.

---

## Skills Over Inline Instructions

Skills load on-demand. CLAUDE.md loads every message. Move specialized instructions into skills.

**Token math:**

- A 200-line skill in CLAUDE.md costs tokens on every single message
- The same 200-line skill as a file in `skills/` costs tokens only when invoked
- Over a 50-message session, that's a 50x difference

**Rule:** If an instruction applies to fewer than half of all sessions, it belongs in a skill, not in CLAUDE.md.

**Current skills (load on demand):**

- `skills/git/SKILL.md` — Git operations
- `skills/python-module/SKILL.md` — Python module creation
- `skills/api-integration/SKILL.md` — Claude API calls
- `skills/cross-platform/SKILL.md` — OS-specific code
- `skills/testing/SKILL.md` — Test writing

---

## Model Selection

Not every task needs the most expensive model.

**Use Opus for:**

- Architecture decisions
- Complex multi-step planning
- Tier 2 canvas analysis prompts
- Director task decomposition
- Debugging subtle cross-component issues

**Use Sonnet for:**

- Implementation (writing code to spec)
- Writing tests
- Documentation updates
- Git operations
- File organization
- Routine refactoring

**Switching mid-session:**

```
/model sonnet
```

Switch to Sonnet for implementation work. Switch back to Opus for planning or debugging.

---

## Extended Thinking Budget

Extended thinking uses output tokens (expensive). Adjust per task.

**High thinking budget (default 31,999):**

- Architecture planning
- Complex debugging
- Multi-file refactoring

**Reduced thinking budget (8,000):**

- Straightforward implementation from spec
- Writing tests for known interfaces
- Documentation
- Git operations

**Disable thinking:**

- Simple file moves or renames
- Config changes
- Adding imports

Set via `/config` or environment variable:

```
MAX_THINKING_TOKENS=8000
```

---

## Agent Team Token Optimization

Agent teams multiply context usage. Each agent has its own context window.

**Rules for teams:**

- Spawn only the agents needed for the current phase
- Keep maximum concurrent agents at 5
- Shut down agents when their tasks complete. Don't let idle agents persist.
- Use the Conductor's task board instead of having agents re-read project docs
- Support-role agents share their team lead's context, not separate sessions

**Communication efficiency:**

- Task board messages should be under 100 words
- Mailbox messages between agents should be factual, not conversational
- When an agent completes a task, it reports: what was done, files modified, tests passing/failing. Nothing else.

---

## Git as Context Reset

Git commits serve as context checkpoints. After committing, the current file state is preserved and the session can be cleared safely.

**Pattern:**

```
1. Complete a unit of work
2. Run tests
3. Commit via git skill
4. /clear
5. Start next task with fresh context
6. If needed, check git log to recall what was done
```

This is the single most effective token-saving technique. It lets you work in short, focused sessions instead of accumulating stale context.

---

## Prompt Engineering for Token Efficiency

**Write prompts like specs. Be precise. Be short.**

```
# Bad (vague, will produce long exploratory response):
Can you look at the capture engine and see if there are any issues?

# Good (specific, bounded response):
In ciu_agent/core/capture_engine.py, check if get_frame() handles
the case where screen capture returns None. If not, add a guard.
```

**Specify output format when it matters:**

```
# Bad:
What's the status of Phase 1?

# Good:
Read docs/taskboard.json. Report Phase 1 status as a table:
task ID, title, status. No commentary.
```

**Avoid open-ended questions that invite long responses:**

```
# Bad:
What do you think about the architecture?

# Good:
Does the Canvas Mapper's Tier 1 analysis handle the case
where a dropdown menu opens? Check docs/architecture.md
section 3.2, state change detection heuristics.
```

---

## Token Budget Targets

| Session Type | Target Budget | Compact At | Clear At |
|-------------|---------------|------------|----------|
| Single task implementation | Under 30K tokens | 70% capacity | Task complete |
| Multi-task phase work | Under 50K tokens | 70% capacity | Every 2-3 tasks |
| Architecture planning | Under 40K tokens | 70% capacity | Plan complete |
| Debugging | Under 40K tokens | 70% capacity | Bug fixed |
| Agent team session | Under 60K total across all agents | 70% per agent | Phase complete |

---

## Token Log

Maintain `docs/token_log.md` with session costs:

```markdown
| Date | Session | Phase | Tasks Completed | Approx Tokens | Notes |
|------|---------|-------|-----------------|---------------|-------|
| 2026-02-19 | 1 | Setup | Project structure | ~5K | Initial setup |
```

Review weekly. Identify which session types are most expensive and optimize those first.

---

## Anti-Patterns (Do Not Do)

- Loading all docs at session start "just in case"
- Asking Claude to "review the entire codebase"
- Running full test suites and dumping all output into context
- Having agents send long status updates to each other
- Keeping stale context after completing a task
- Using CLAUDE.md as a comprehensive manual
- Re-reading files that haven't changed
- Asking open-ended questions that produce long responses when a specific answer is needed
- Using `@file` references in CLAUDE.md
- Letting auto-compact trigger at 95% instead of manually compacting at 70%
- Spawning agents that sit idle waiting for work
- Writing conversational mailbox messages between agents instead of factual reports
