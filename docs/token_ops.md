# CIU Agent — Token Operations Policy

## Purpose

This document is a binding operational policy. Every Claude Code session, agent, sub-agent, and team member working on the CIU Agent project must follow these rules. The Token Warden agent (defined in `docs/agents.md`) enforces compliance.

---

## MCP Configuration

### Required MCPs

Install these before starting any development work:

```bash
# GitHub MCP — git operations without shell overhead
claude mcp add github --scope project -e GITHUB_TOKEN -- npx -y @modelcontextprotocol/server-github

# Context7 — on-demand library docs (opencv, mss, pynput, httpx, pytest)
claude mcp add context7 --scope project -- npx -y @upstash/context7-mcp@latest

# Sequential Thinking — structured decomposition for complex tasks
claude mcp add sequential-thinking --scope project -- npx -y @modelcontextprotocol/server-sequential-thinking

# Memory MCP — persistent knowledge graph across sessions
claude mcp add memory --scope project -- npx -y @modelcontextprotocol/server-memory
```

### Optional MCPs

```bash
# CC Token Saver — offload simple tasks to local LLM (requires local model running)
# Only install if a local LLM (e.g. Qwen 2.5-7B via LM Studio) is available
claude mcp add cc-token-saver --scope project -- python D:\projects\ciu_agent\tools\cc_token_saver_mcp\server.py
```

### MCP Tool Search (Mandatory)

Enable lazy loading so MCP tool schemas don't bloat every message:

```json
// .claude/settings.json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "ENABLE_TOOL_SEARCH": "auto",
    "MAX_MCP_OUTPUT_TOKENS": "15000"
  }
}
```

---

## Task-to-Tool Routing

Every task type maps to a specific token-saving approach. Agents must use the cheapest effective method.

### File Operations

| Task | Method | Why |
|---|---|---|
| Read a file under 100 lines | Direct read | Small enough, no optimization needed |
| Read a file over 100 lines | Grep for relevant section, then read line range | Avoid loading 500 lines when you need 20 |
| Read multiple files for context | Subagent reads all files, returns summary to scratchpad | Keeps main context clean |
| Check if a file contains X | `grep -n "X" filepath` | One line of output vs entire file |
| Compare two implementations | Subagent reads both, returns diff summary | Two large files stay out of main context |

### Documentation Lookups

| Task | Method | Why |
|---|---|---|
| Look up OpenCV function usage | Context7 MCP | Fetches only the relevant section, not entire docs |
| Look up mss or pynput API | Context7 MCP | Same — targeted retrieval |
| Look up project architecture | Read specific section of `docs/architecture.md` | Progressive disclosure |
| Look up agent responsibilities | Read `docs/agents.md` | Only when agent assignment is needed |
| Look up phase deliverables | Read `docs/phases.md` | Only when planning or reviewing phase work |

### Git Operations

| Task | Method | Why |
|---|---|---|
| Commit and push | GitHub MCP `create_commit` + `push` | Structured API, no shell parsing overhead |
| Check status | `git status --short` | Short flag reduces output |
| View recent history | `git log --oneline -5` | Five lines, not full log |
| Create branch | GitHub MCP or `git checkout -b name` | Either works, MCP avoids shell context |
| Create PR | GitHub MCP `create_pull_request` | Direct API, no browser needed |
| Check CI status | GitHub MCP `get_workflow_runs` | Avoids pulling full workflow logs |

### Complex Reasoning

| Task | Method | Why |
|---|---|---|
| Decompose a build phase into tasks | Sequential Thinking MCP | Structured step output, compact result |
| Debug a cross-component issue | Sequential Thinking MCP + subagent investigation | Isolate reasoning from file exploration |
| Plan error recovery strategy | Sequential Thinking MCP | Returns structured decision tree |
| Architect a new component interface | Direct reasoning (Opus model) | Needs full creative reasoning, no shortcut |

### Testing

| Task | Method | Why |
|---|---|---|
| Run full test suite | `pytest tests/ -v 2>&1 \| tail -40` | Only see failures and summary |
| Run single test file | `pytest tests/test_capture.py -v 2>&1 \| tail -20` | Bounded output |
| Run tests and check pass/fail only | `pytest tests/ --tb=no -q` | Minimal output: "5 passed, 0 failed" |
| Debug a failing test | Run single test with full traceback, read only the relevant file section | Don't dump entire files for one failure |

### Knowledge Persistence

| Task | Method | Why |
|---|---|---|
| Store an architecture decision | Memory MCP `create_entity` + `add_relation` | Survives session clears |
| Store a resolved design question | Memory MCP `create_entity` | Don't re-debate settled questions |
| Recall what was decided about X | Memory MCP `search_nodes` | Instant lookup vs re-reading docs |
| Track which tasks are complete | Memory MCP or `docs/taskboard.json` | Persists across sessions |
| Record a gotcha or workaround | Memory MCP `create_entity` with "gotcha" tag | Available to all future sessions |

---

## Mandatory Procedures Per Task Lifecycle

### Before Starting a Task

1. Check Memory MCP for any stored context about this task or component
2. Read only the docs relevant to this specific task (not all docs)
3. If task requires understanding existing code, use `grep` first to locate relevant sections
4. Set model appropriately: Opus for planning/debugging, Sonnet for implementation

### During a Task

5. Write findings to scratchpad (`/tmp/scratchpad.md`) if exploring multiple files
6. Use subagents for any investigation that requires reading 3+ files
7. Truncate all command output: `| tail -30` for tests, `--short` for git, `-L 2` for tree
8. If a library API is needed, use Context7 MCP instead of searching the web
9. If reasoning is complex, use Sequential Thinking MCP to structure it externally
10. Monitor context: if approaching 70%, run `/compact` with specific preservation instructions

### After Completing a Task

11. Store any decisions, gotchas, or findings in Memory MCP
12. Commit via GitHub MCP or git skill
13. Update `docs/taskboard.json`
14. If switching to a different task domain, run `/clear`
15. Log approximate token usage to `docs/token_log.md`

---

## Agent-Specific Token Rules

### Conductor / Team Lead

- Use Sequential Thinking MCP for all phase decomposition
- Never read source code directly. Use subagents for codebase investigation.
- Task board updates should be under 50 words per task
- Spawn agents only when their tasks are unblocked. Shut down when complete.

### Architect

- Use Memory MCP to store all design decisions
- Before making a decision, query Memory MCP for prior decisions on the same topic
- Use Opus model only. Architecture reasoning justifies the cost.
- Keep review comments under 100 words per file

### Platform Engineer

- Use Context7 MCP for all OS API lookups (ctypes, Xlib, Quartz, etc.)
- Use subagents for each platform implementation (one subagent per OS)
- Never load all three platform files into one context

### Capture Specialist

- Use Context7 MCP for OpenCV and mss documentation
- Test output must always be truncated
- Frame data and screenshots must never enter the context window (write to disk, reference by path)

### Canvas Specialist

- API prompts for Tier 2 analysis are high-value. Use Opus for prompt design.
- Use Sonnet for parsing and registry management code.
- Store zone classification rules in Memory MCP so they don't need rediscovery each session.

### Brush Specialist

- Pure implementation work. Use Sonnet.
- Geometry calculations need no external docs. Don't look up basic math.
- Test with `--tb=short` flag to limit traceback output.

### Director Specialist

- Use Sequential Thinking MCP for task decomposition logic design
- Use Memory MCP to store task decomposition patterns that work
- Error recovery strategies should be stored in Memory MCP after design

### Test Engineer

- Always run tests with output limits: `--tb=short -q` for pass/fail, full output only for debugging
- Use subagent to run full test suite and return summary
- Never dump full test output into the team lead's context

### Documentation Agent

- Use Sonnet exclusively
- Reduce thinking budget to 4000 for doc updates
- Scan files with `grep` for docstring presence before reading full files

---

## Compaction Rules

When running `/compact`, always provide instructions:

**For implementation sessions:**
```
/compact Preserve: current task ID, file paths modified, function signatures created, test results. Discard: file contents, exploration paths, verbose outputs, old task discussions.
```

**For planning sessions:**
```
/compact Preserve: phase plan, task dependencies, unresolved questions, agent assignments. Discard: background research, doc contents already committed, rejected approaches.
```

**For debugging sessions:**
```
/compact Preserve: bug description, root cause hypothesis, files involved, fix applied, test result. Discard: failed investigation paths, irrelevant file reads, stack traces from resolved errors.
```

---

## CC Token Saver Delegation Rules

If CC Token Saver MCP is available (local LLM running), delegate these tasks to it:

**Delegate to local LLM:**

- Generating docstrings from function signatures
- Formatting code comments
- Writing simple boilerplate (imports, __init__.py files)
- Generating test function stubs from class interfaces
- Simple text transformations (rename variable across a small file)
- Generating type hint annotations for existing functions
- Writing commit messages from a diff summary

**Keep on Claude (never delegate):**

- Architecture decisions
- Cross-component reasoning
- API prompt design (Tier 2 canvas analysis)
- Error recovery logic
- Task decomposition
- Anything requiring knowledge of the full system design
- Code that touches component interfaces

---

## Token Budget Enforcement

The Token Warden agent monitors and enforces these budgets:

| Session Type | Hard Ceiling | Compact Trigger | Clear Trigger |
|---|---|---|---|
| Single task (Sonnet) | 30K tokens | 21K (70%) | Task complete |
| Single task (Opus) | 40K tokens | 28K (70%) | Task complete |
| Multi-task session | 50K tokens | 35K (70%) | Every 2-3 tasks |
| Agent team session | 60K total | 42K total | Phase complete |
| Per-agent in team | 15K each | 10K each | Task complete |

If any agent exceeds its per-agent budget without compacting, the Token Warden flags it to the Conductor for review.

---

## Weekly Token Review

Every week (or every 5 sessions, whichever comes first):

1. Review `docs/token_log.md`
2. Identify the most expensive session types
3. Check if any agent consistently exceeds budgets
4. Look for patterns: are certain tasks wasting tokens on repeated file reads?
5. Update this policy if new optimizations are discovered
6. Store findings in Memory MCP under "token-optimization" entity
