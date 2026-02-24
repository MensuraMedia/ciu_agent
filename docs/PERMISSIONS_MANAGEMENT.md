# Permissions Management for Autonomous Agent Teams

> A universal framework for granting, restricting, escalating, and auditing
> permissions across multi-agent systems.  Applicable to any project where
> autonomous agents collaborate — from GUI automation to code generation to
> infrastructure management.

---

## Table of Contents

1. [Why Permissions Matter](#1-why-permissions-matter)
2. [Core Concepts](#2-core-concepts)
3. [Agent Roles and Hierarchy](#3-agent-roles-and-hierarchy)
4. [Permission Taxonomy](#4-permission-taxonomy)
5. [Object Permission Matrix](#5-object-permission-matrix)
6. [Freedom of Movement](#6-freedom-of-movement)
7. [Dynamic Escalation and Delegation](#7-dynamic-escalation-and-delegation)
8. [Permission Profiles by Role](#8-permission-profiles-by-role)
9. [Multi-Agent Coordination](#9-multi-agent-coordination)
10. [Security Model](#10-security-model)
11. [Implementing Permissions in Practice](#11-implementing-permissions-in-practice)
12. [Universal Patterns](#12-universal-patterns)

---

## 1. Why Permissions Matter

Autonomous agents are powerful.  A single agent with unrestricted access can
read every file, execute arbitrary commands, make API calls, modify shared
state, and push code — all in seconds.  When you multiply that power across
a team of five or ten agents working in parallel, the risk surface expands
proportionally.

Permissions exist to solve three problems simultaneously:

1. **Safety** — Prevent agents from taking destructive or irreversible
   actions without human awareness.  An agent should never `rm -rf /` or
   `git push --force` to `main` unless a human explicitly authorised it.

2. **Coordination** — When multiple agents operate on the same codebase,
   uncoordinated writes create merge conflicts, overwritten work, and
   subtle regressions.  Permissions define who can write where, preventing
   two agents from editing the same file at the same time.

3. **Accountability** — When something goes wrong (a test breaks, a deploy
   fails, a secret is leaked), the permission audit trail tells you which
   agent took which action, whether it was authorised, and who granted
   the permission.

Without a permission model, teams of agents become unpredictable.  With one,
they become a disciplined workforce that operates at machine speed while
respecting human-defined boundaries.

---

## 2. Core Concepts

### 2.1 Subjects, Objects, and Actions

Every permission decision involves three elements:

| Element    | Definition                                        | Examples                                  |
|------------|---------------------------------------------------|-------------------------------------------|
| **Subject** | The agent (or role) requesting the action        | Conductor, Architect, Worker, Observer    |
| **Object**  | The resource being acted upon                    | A file, directory, API endpoint, branch   |
| **Action**  | The operation being performed                    | Read, write, create, delete, execute      |

A permission rule is a triple: **(Subject, Action, Object) → Allow | Deny**.

```
(Conductor,  write,  docs/taskboard.json)  → Allow
(Worker,     delete, ciu_agent/core/*.py)   → Deny
(Architect,  write,  docs/architecture.md)  → Allow
(Observer,   read,   *)                     → Allow
(Observer,   write,  *)                     → Deny
```

### 2.2 Principle of Least Privilege

Every agent starts with the minimum permissions required to accomplish its
assigned task.  Additional permissions are granted on demand through
escalation, not pre-assigned "just in case."

This means:
- A Worker agent assigned to write `ciu_agent/core/capture_engine.py` gets
  write access to that file and its test file — not to the entire `core/`
  directory.
- An Observer agent can read everything but write nothing.
- A Conductor can assign tasks and update the task board but cannot modify
  application code directly.

### 2.3 Scope and Duration

Permissions have both scope (what they cover) and duration (how long they
last):

| Duration       | Description                                     | Use Case                                  |
|----------------|--------------------------------------------------|-------------------------------------------|
| **Session**    | Active for the current session only              | Default for most grants                   |
| **Task**       | Active only while a specific task is in progress | Worker file write access                  |
| **Permanent**  | Persists across sessions (stored in config)      | Conductor's task board access             |
| **One-shot**   | Expires after a single use                       | Emergency force-push to fix a broken main |

### 2.4 Explicit vs Implicit Permissions

- **Explicit permissions** are stated in configuration files or granted by
  a human during a session.  They are auditable and revocable.
- **Implicit permissions** are inherited from role definitions.  A Conductor
  implicitly has read access to all project files because its role requires
  understanding the full codebase.
- **Ambient permissions** come from the environment (e.g., the OS user
  account the agent runs under).  These should be minimised through
  sandboxing.

---

## 3. Agent Roles and Hierarchy

### 3.1 Role Definitions

Agent teams use a hierarchical role model.  Each role has a defined scope
of authority, a set of default permissions, and a clear escalation path.

#### Team Lead (Conductor)

The Conductor is the orchestration layer.  It does not write application
code.  It plans work, assigns tasks to agents, tracks progress, resolves
conflicts, and ensures the build moves forward in the correct order.

**Authority:**
- Full read access to the entire project
- Write access to coordination files (task board, session notes, status)
- Spawn and shutdown authority over all team members
- Task assignment and reassignment
- Conflict resolution (with Architect escalation for design decisions)
- Override authority for Token Warden recommendations (logged)

**Restrictions:**
- Cannot write application code (`ciu_agent/**/*.py`)
- Cannot run destructive git commands (`push --force`, `reset --hard`)
- Cannot modify architectural specifications without Architect approval

#### Architect

The Architect makes design decisions.  It reviews interfaces, resolves
cross-domain conflicts, and ensures all work aligns with the system
architecture.

**Authority:**
- Full read access to the entire project
- Write access to architecture and design documents
- Veto power over any implementation that violates architectural constraints
- Authority to split cross-domain tasks into single-domain subtasks
- Review and approval authority for interface changes

**Restrictions:**
- Does not write application code directly (reviews, not implements)
- Cannot override the Conductor's task scheduling
- Cannot spawn or shutdown agents (that is the Conductor's role)

#### Worker (Specialist)

Workers are domain-specific implementation agents.  Each Worker owns a
specific area of the codebase and implements tasks assigned by the
Conductor.

**Authority:**
- Read access to the entire project (needed for understanding context)
- Write access to files within their owned domain
- Write access to test files corresponding to their domain
- Execute tests related to their domain
- Create new files within their domain when justified by the task
- Use the git skill to commit their own completed work

**Restrictions:**
- Cannot write to files outside their owned domain
- Cannot modify shared configuration without Conductor approval
- Cannot spawn sub-agents unless explicitly authorised
- Cannot push to remote (Conductor coordinates merges and pushes)
- Maximum 2 concurrent tasks

#### Observer

Observers are read-only agents.  They monitor, analyse, and report but
never modify.  Useful for auditing, documentation generation, and quality
analysis.

**Authority:**
- Full read access to the entire project
- Read access to git history and logs
- Authority to generate reports and recommendations

**Restrictions:**
- Cannot write any files
- Cannot execute commands that modify state
- Cannot spawn agents or assign tasks

#### Researcher

Researchers investigate questions, explore approaches, and provide
analysis.  They read broadly and may run non-destructive commands but
never modify the project.

**Authority:**
- Full read access to the entire project
- Execute read-only commands (grep, find, type-checking, linting)
- Web search and API documentation lookups
- Authority to create temporary scratch files in a designated area

**Restrictions:**
- Cannot write to any project files (except scratch area)
- Cannot run tests that modify state
- Cannot push code or create branches

#### Token Warden

A specialised Observer that monitors API token consumption, enforces
budgets, and flags violations.

**Authority:**
- Full read access to token logs and configuration
- Write access to `docs/token_log.md` and `docs/token_violations.md`
- Authority to emit warnings that the Conductor must acknowledge
- Authority to recommend session termination when budgets are exceeded

**Restrictions:**
- Cannot block or terminate agents directly
- Cannot modify application code or tests
- Recommendations are advisory unless the Conductor explicitly delegates
  enforcement authority

### 3.2 Hierarchy and Reporting Lines

```
Human Operator (ultimate authority)
│
├── Conductor (Team Lead)
│   ├── Token Warden (advisory)
│   ├── Architect (design authority)
│   ├── Worker: Platform Engineer
│   │   ├── Sub-worker: Linux Impl
│   │   ├── Sub-worker: Windows Impl
│   │   └── Sub-worker: macOS Impl
│   ├── Worker: Capture Specialist
│   ├── Worker: Canvas Specialist
│   ├── Worker: Brush Specialist
│   ├── Worker: Director Specialist
│   ├── Worker: Test Engineer
│   │   ├── Sub-worker: Unit Writer
│   │   ├── Sub-worker: Integration Writer
│   │   └── Sub-worker: Mock Builder
│   ├── Observer: Documentation
│   └── Researcher (as needed)
```

**Reporting rules:**
- Sub-agents report to their parent agent only
- Parent agents report to the Conductor
- The Conductor reports to the Human Operator
- The Architect has advisory authority across all agents but reports to the
  Conductor for scheduling purposes
- The Token Warden reports to both the Conductor and the Human Operator

---

## 4. Permission Taxonomy

Permissions are organised into five categories.  Each category addresses a
different type of resource or action.

### 4.1 File System Permissions

Control what agents can do with files and directories.

| Permission      | Description                                        |
|-----------------|----------------------------------------------------|
| `fs:read`       | Read file contents                                 |
| `fs:write`      | Modify existing files                              |
| `fs:create`     | Create new files                                   |
| `fs:delete`     | Delete files                                       |
| `fs:rename`     | Rename or move files                               |
| `fs:glob`       | Search for files by pattern                        |
| `fs:grep`       | Search file contents                               |

**Scoping:** File system permissions are scoped to paths using glob
patterns:

```yaml
permissions:
  platform-engineer:
    fs:read:  "*"                          # Read anything
    fs:write: "ciu_agent/platform/**"      # Write only in platform/
    fs:write: "tests/test_platform_*.py"   # Write platform tests
    fs:create: "ciu_agent/platform/**"     # Create files in platform/
    fs:delete: null                        # Cannot delete files
```

### 4.2 Execution Permissions

Control what commands and processes agents can run.

| Permission      | Description                                        |
|-----------------|----------------------------------------------------|
| `exec:python`   | Run Python scripts and modules                     |
| `exec:test`     | Run test suites                                    |
| `exec:lint`     | Run linters and formatters                         |
| `exec:typecheck`| Run type checkers                                  |
| `exec:shell`    | Run arbitrary shell commands (high privilege)       |
| `exec:install`  | Install packages and dependencies                  |

**Risk levels:**

```
Low risk:    exec:lint, exec:typecheck, exec:test
Medium risk: exec:python, exec:install
High risk:   exec:shell (arbitrary commands)
```

Workers should typically have `exec:test` and `exec:lint` but NOT
`exec:shell`.  Only the Conductor and explicitly authorised agents should
have `exec:shell`.

### 4.3 Git Permissions

Control version control operations.

| Permission        | Description                                      |
|-------------------|--------------------------------------------------|
| `git:status`      | View working tree status                         |
| `git:log`         | View commit history                              |
| `git:diff`        | View file differences                            |
| `git:add`         | Stage files for commit                           |
| `git:commit`      | Create commits                                   |
| `git:branch`      | Create and switch branches                       |
| `git:push`        | Push to remote repository                        |
| `git:pull`        | Pull from remote repository                      |
| `git:merge`       | Merge branches                                   |
| `git:force-push`  | Force push (destructive, requires escalation)    |
| `git:reset-hard`  | Hard reset (destructive, requires escalation)    |

**Default assignments:**

```
Observer:    git:status, git:log, git:diff
Worker:      git:status, git:log, git:diff, git:add, git:commit
Conductor:   All git permissions EXCEPT git:force-push, git:reset-hard
Architect:   git:status, git:log, git:diff
```

`git:force-push` and `git:reset-hard` always require Human Operator
approval, regardless of role.

### 4.4 API Permissions

Control external API calls (e.g., Claude API for vision analysis and task
planning).

| Permission           | Description                                   |
|----------------------|-----------------------------------------------|
| `api:vision`         | Make Claude API vision analysis calls          |
| `api:planning`       | Make Claude API task planning calls            |
| `api:web-search`     | Perform web searches                           |
| `api:external`       | Call external services (webhooks, etc.)         |

**Budget constraints:**

API permissions include budget limits:

```yaml
api:vision:
  allowed: true
  max_calls_per_session: 50
  max_tokens_per_call: 4096
  timeout_seconds: 60

api:planning:
  allowed: true
  max_calls_per_session: 30
  max_tokens_per_call: 8192
  timeout_seconds: 30
```

### 4.5 Coordination Permissions

Control inter-agent communication and team operations.

| Permission              | Description                                 |
|-------------------------|---------------------------------------------|
| `coord:spawn`           | Create new agents                           |
| `coord:shutdown`        | Terminate agents                            |
| `coord:assign`          | Assign tasks to agents                      |
| `coord:reassign`        | Reassign tasks between agents               |
| `coord:broadcast`       | Send messages to all team members            |
| `coord:message`         | Send direct messages to specific agents      |
| `coord:escalate`        | Escalate issues up the hierarchy             |
| `coord:override`        | Override another agent's decision            |
| `coord:task-create`     | Create new tasks on the task board           |
| `coord:task-update`     | Update task status                          |

**Default assignments:**

```
Conductor:  All coordination permissions
Architect:  coord:message, coord:escalate, coord:override (design only)
Worker:     coord:message, coord:escalate, coord:task-update (own tasks)
Observer:   coord:message (read-only reports)
Researcher: coord:message, coord:escalate
```

---

## 5. Object Permission Matrix

The Object Permission Matrix is a comprehensive mapping of every role
to every resource category.  It serves as the single source of truth for
"who can do what to which resource."

### 5.1 File Resources

| Resource                          | Conductor | Architect | Worker (own) | Worker (other) | Observer | Researcher |
|-----------------------------------|-----------|-----------|--------------|----------------|----------|------------|
| `ciu_agent/core/*.py`             | Read      | Read      | Read+Write   | Read           | Read     | Read       |
| `ciu_agent/platform/*.py`         | Read      | Read      | Read+Write   | Read           | Read     | Read       |
| `ciu_agent/config/*.py`           | Read      | Read+Write| Read         | Read           | Read     | Read       |
| `ciu_agent/models/*.py`           | Read      | Read+Write| Read+Write   | Read           | Read     | Read       |
| `tests/*.py`                      | Read      | Read      | Read+Write   | Read           | Read     | Read       |
| `docs/*.md`                       | Read+Write| Read+Write| Read         | Read           | Read     | Read       |
| `docs/architecture.md`            | Read      | Read+Write| Read         | Read           | Read     | Read       |
| `docs/taskboard.json`             | Read+Write| Read      | Read         | Read           | Read     | Read       |
| `CLAUDE.md`                       | Read      | Read+Write| Read         | Read           | Read     | Read       |
| `.claude/**`                      | Read+Write| Read      | Read         | Read           | Read     | Read       |
| `requirements.txt`                | Read+Write| Read+Write| Read         | Read           | Read     | Read       |
| `.gitignore`                      | Read+Write| Read+Write| Read         | Read           | Read     | Read       |
| `sessions/**`                     | Read      | Read      | Read+Write   | Read           | Read     | Read       |

### 5.2 Command Resources

| Command Category    | Conductor | Architect | Worker | Observer | Researcher |
|---------------------|-----------|-----------|--------|----------|------------|
| `python -m pytest`  | Execute   | —         | Execute| —        | —          |
| `python -m mypy`    | Execute   | —         | Execute| —        | Execute    |
| `python -m ruff`    | Execute   | —         | Execute| —        | Execute    |
| `pip install`       | Execute   | —         | —      | —        | —          |
| `git commit`        | Execute   | —         | Execute| —        | —          |
| `git push`          | Execute   | —         | —      | —        | —          |
| `git branch`        | Execute   | —         | Execute| —        | —          |
| `git push --force`  | Escalate  | —         | —      | —        | —          |
| `rm / del`          | Escalate  | —         | —      | —        | —          |
| Arbitrary shell     | Execute   | —         | —      | —        | —          |

### 5.3 Domain Ownership Map

Workers are assigned domains.  A domain is a set of file paths that the
Worker has write access to.  Domains are non-overlapping — no two Workers
own the same file.

```
platform-engineer:
  owns:
    - ciu_agent/platform/**
    - tests/test_platform*.py
    - tests/conftest_platform.py

capture-specialist:
  owns:
    - ciu_agent/core/capture_engine.py
    - ciu_agent/core/replay_buffer.py
    - tests/test_capture*.py
    - tests/test_replay*.py

canvas-specialist:
  owns:
    - ciu_agent/core/canvas_mapper.py
    - ciu_agent/core/zone_registry.py
    - ciu_agent/core/zone_tracker.py
    - ciu_agent/core/state_classifier.py
    - ciu_agent/core/tier1_analyzer.py
    - ciu_agent/core/tier2_analyzer.py
    - tests/test_canvas*.py
    - tests/test_zone*.py
    - tests/test_state*.py
    - tests/test_tier*.py

brush-specialist:
  owns:
    - ciu_agent/core/brush_controller.py
    - ciu_agent/core/motion_planner.py
    - ciu_agent/core/action_executor.py
    - tests/test_brush*.py
    - tests/test_motion*.py
    - tests/test_action*.py

director-specialist:
  owns:
    - ciu_agent/core/director.py
    - ciu_agent/core/task_planner.py
    - ciu_agent/core/step_executor.py
    - ciu_agent/core/error_classifier.py
    - tests/test_director*.py
    - tests/test_task_planner*.py
    - tests/test_step_executor*.py
    - tests/test_error*.py

test-engineer:
  owns:
    - tests/conftest.py
    - tests/test_integration*.py
    - tests/fixtures/**
```

---

## 6. Freedom of Movement

"Freedom of movement" describes how much autonomy an agent has to operate
without asking for permission at every step.  High freedom means the agent
can work independently for long stretches.  Low freedom means the agent
must check in frequently.

### 6.1 Autonomy Levels

| Level | Name            | Description                                           |
|-------|-----------------|-------------------------------------------------------|
| 0     | **Locked**       | Agent cannot act. Waiting for explicit assignment.    |
| 1     | **Supervised**   | Every action requires approval before execution.      |
| 2     | **Guided**       | Agent can act within approved plan; deviations need approval. |
| 3     | **Autonomous**   | Agent can act freely within its domain boundaries.    |
| 4     | **Unrestricted** | Agent can act across domains (reserved for Conductor). |

**Default autonomy by role:**

```
Conductor:     Level 4 (Unrestricted) — can coordinate across all domains
Architect:     Level 3 (Autonomous)   — free within design domain
Worker:        Level 3 (Autonomous)   — free within owned domain
Observer:      Level 3 (Autonomous)   — free to read and report
Researcher:    Level 3 (Autonomous)   — free to investigate
Token Warden:  Level 3 (Autonomous)   — free to monitor and report
Sub-agent:     Level 2 (Guided)       — follows parent agent's plan
```

### 6.2 Movement Constraints

Even at Level 3 (Autonomous), agents operate within boundaries:

**Spatial boundaries:** An agent can only write to files within its owned
domain.  It can read anywhere but cannot create, modify, or delete files
outside its scope.

**Temporal boundaries:** An agent should complete its assigned task within
a reasonable timeframe.  If a task exceeds its expected scope, the agent
must escalate to the Conductor rather than expanding scope autonomously.

**Action boundaries:** An agent can perform any action within its
permission set.  If it needs to perform an action outside its permissions
(e.g., a Worker needs to modify a shared config file), it must escalate.

**Communication boundaries:** An agent communicates with its parent and
siblings.  It does not bypass the hierarchy to message agents in other
parts of the tree.

### 6.3 Granting Additional Freedom

The Conductor can temporarily elevate an agent's autonomy:

```python
# Conductor grants temporary cross-domain access
escalation = PermissionGrant(
    subject="brush-specialist",
    action="fs:write",
    object="ciu_agent/core/canvas_mapper.py",
    duration="task",
    reason="Brush specialist needs to add event hooks to CanvasMapper",
    granted_by="conductor",
    task_id="P3-012",
)
```

This grant:
- Is scoped to a specific file (`canvas_mapper.py`)
- Expires when the task (`P3-012`) completes
- Is logged with the reason and granting authority
- Can be revoked by the Conductor at any time

### 6.4 Revoking Freedom

Permissions can be revoked in three scenarios:

1. **Task completion** — Task-scoped permissions expire automatically.
2. **Violation** — If an agent attempts an unauthorised action, the
   Conductor may reduce its autonomy level.
3. **Conflict** — If two agents' work conflicts, the Conductor may
   temporarily lock one agent (Level 0) while the conflict is resolved.

---

## 7. Dynamic Escalation and Delegation

### 7.1 Escalation

Escalation is the process of requesting higher-level authority to perform
an action outside the agent's current permissions.

**Escalation path:**

```
Sub-agent → Parent Agent → Conductor → Human Operator
```

**When to escalate:**

- The agent needs to write to a file outside its domain
- The agent encounters an error it cannot resolve within its scope
- The agent's task has expanded beyond the original scope
- The agent needs to run a command not in its permission set
- A design decision is required (escalate to Architect via Conductor)

**Escalation request format:**

```json
{
  "type": "escalation",
  "from": "brush-specialist",
  "to": "conductor",
  "action_needed": "fs:write",
  "target": "ciu_agent/core/canvas_mapper.py",
  "reason": "Need to add ZoneEvent callback registration to CanvasMapper.process_frame()",
  "urgency": "normal",
  "task_id": "P3-012",
  "alternatives": [
    "Architect could add the callback hook instead",
    "Canvas specialist could add it as a separate task"
  ]
}
```

### 7.2 Delegation

Delegation is the reverse of escalation: a higher-authority agent
temporarily grants some of its permissions to a lower-level agent.

**Delegation rules:**

1. An agent can only delegate permissions it currently holds.
2. Delegated permissions cannot exceed the delegator's scope.
3. Delegations have a mandatory expiration (task or session).
4. Delegations are logged and auditable.
5. The delegator remains accountable for actions taken under delegation.

**Example: Conductor delegates push authority to Worker**

```json
{
  "type": "delegation",
  "from": "conductor",
  "to": "test-engineer",
  "permission": "git:push",
  "scope": "branch:test/integration-suite-*",
  "duration": "session",
  "reason": "Test engineer needs to push test branches for CI validation",
  "constraints": ["Cannot push to main", "Cannot force push"]
}
```

### 7.3 Automatic Escalation Triggers

Some conditions should trigger automatic escalation without the agent
needing to decide:

| Condition                              | Escalates To    |
|----------------------------------------|-----------------|
| File write outside owned domain         | Conductor       |
| Test failure in another domain          | Conductor       |
| API budget exceeds 80%                  | Token Warden    |
| Task duration exceeds 2x estimate       | Conductor       |
| Merge conflict detected                 | Conductor       |
| Destructive command attempted           | Human Operator  |
| Authentication failure                  | Human Operator  |
| Dependency installation needed          | Conductor       |

---

## 8. Permission Profiles by Role

### 8.1 Conductor Profile

```yaml
role: conductor
autonomy_level: 4
permissions:
  filesystem:
    read: "*"
    write:
      - "docs/**"
      - ".claude/**"
      - "requirements.txt"
      - ".gitignore"
    create:
      - "docs/**"
      - ".claude/**"
    delete: null  # Escalate to Human Operator

  execution:
    allowed:
      - "python -m pytest *"
      - "python -m mypy *"
      - "python -m ruff *"
      - "pip install *"
      - "git *"
    denied:
      - "git push --force *"
      - "git reset --hard *"
      - "rm -rf *"
      - "del /s /q *"

  git:
    allowed: [status, log, diff, add, commit, branch, push, pull, merge, tag, fetch, stash, rebase]
    denied: [force-push, reset-hard]

  api:
    vision: { allowed: true, max_calls: 50 }
    planning: { allowed: true, max_calls: 30 }

  coordination:
    allowed: [spawn, shutdown, assign, reassign, broadcast, message, escalate, override, task-create, task-update]
```

### 8.2 Architect Profile

```yaml
role: architect
autonomy_level: 3
permissions:
  filesystem:
    read: "*"
    write:
      - "docs/architecture.md"
      - "docs/phases.md"
      - "CLAUDE.md"
      - "ciu_agent/config/**"
      - "ciu_agent/models/**"
    create:
      - "docs/**"
    delete: null

  execution:
    allowed:
      - "python -m mypy *"
      - "python -m ruff check *"
    denied:
      - "python -m pytest *"  # Architect reviews, does not test
      - "pip install *"
      - "git push *"

  git:
    allowed: [status, log, diff]
    denied: [add, commit, push, branch]  # Architect advises, Conductor commits

  coordination:
    allowed: [message, escalate, override]
    denied: [spawn, shutdown, assign, broadcast]
```

### 8.3 Worker Profile

```yaml
role: worker
autonomy_level: 3
permissions:
  filesystem:
    read: "*"
    write: "{owned_domain}/**"  # Resolved per worker instance
    create: "{owned_domain}/**"
    delete: null  # Workers don't delete, they deprecate

  execution:
    allowed:
      - "python -m pytest tests/{owned_test_files}"
      - "python -m mypy {owned_domain}/"
      - "python -m ruff check {owned_domain}/"
      - "python -m ruff format {owned_domain}/"
    denied:
      - "pip install *"
      - "git push *"
      - "rm *"
      - "del *"

  git:
    allowed: [status, log, diff, add, commit, branch]
    denied: [push, merge, force-push, reset-hard]

  coordination:
    allowed: [message, escalate, task-update]
    denied: [spawn, shutdown, assign, broadcast, override]
```

### 8.4 Observer Profile

```yaml
role: observer
autonomy_level: 3
permissions:
  filesystem:
    read: "*"
    write: null
    create: null
    delete: null

  execution:
    allowed: []
    denied: ["*"]  # Observers do not execute

  git:
    allowed: [status, log, diff]
    denied: [add, commit, push, branch, merge]

  coordination:
    allowed: [message]
    denied: [spawn, shutdown, assign, escalate, broadcast, override]
```

### 8.5 Researcher Profile

```yaml
role: researcher
autonomy_level: 3
permissions:
  filesystem:
    read: "*"
    write:
      - "scratch/**"  # Temporary scratch area
    create:
      - "scratch/**"
    delete:
      - "scratch/**"

  execution:
    allowed:
      - "python -m mypy *"
      - "python -m ruff check *"
      - "grep *"
      - "find *"
    denied:
      - "python -m pytest *"
      - "pip install *"
      - "git commit *"
      - "git push *"

  git:
    allowed: [status, log, diff]
    denied: [add, commit, push, branch, merge]

  coordination:
    allowed: [message, escalate]
    denied: [spawn, shutdown, assign, broadcast, override]
```

---

## 9. Multi-Agent Coordination

### 9.1 Concurrent Access Control

When multiple agents work in parallel, file access must be coordinated
to prevent conflicts.

**Rule 1: Non-overlapping domains**

The primary mechanism for preventing conflicts is non-overlapping domain
ownership.  If no two Workers own the same file, they can work in parallel
without coordination.

**Rule 2: Lock-before-write for shared files**

Some files are shared (e.g., `requirements.txt`, `docs/taskboard.json`).
For these files, agents must request a write lock from the Conductor before
modifying:

```
1. Worker requests: "I need to update requirements.txt to add httpx"
2. Conductor checks: Is anyone else modifying requirements.txt?
3. If clear: Conductor grants write lock with expiration
4. Worker modifies the file
5. Worker releases the lock (or it expires)
```

**Rule 3: Read-any, write-own**

Any agent can read any file at any time.  Reads never require locks.
Writes require either domain ownership or an explicit grant.

### 9.2 Task Dependency Enforcement

Permissions interact with task dependencies.  An agent cannot start a
task that is blocked by an incomplete upstream task, even if it has the
file-level permissions to do so.

```
Task P2-003 (Canvas Specialist): Implement ZoneRegistry
  blocked_by: P2-001 (Zone model definition)

Even though Canvas Specialist has fs:write for zone_registry.py,
it cannot start P2-003 until P2-001 is marked complete by the Conductor.
```

This is a **coordination permission**, not a **file permission**.  The
Conductor enforces it through the task board, not through file locks.

### 9.3 Cross-Domain Collaboration

Sometimes a task requires changes across multiple domains.  The Conductor
handles this by splitting the task:

```
Original task: "Add cursor event callbacks to CanvasMapper"

Split into:
  P3-012a (Canvas Specialist): Add callback registration API to CanvasMapper
  P3-012b (Brush Specialist):  Register brush event handlers via the new API

P3-012b blocked_by P3-012a

Each agent works within its own domain.
No cross-domain permissions needed.
```

If splitting is not feasible, the Conductor grants temporary cross-domain
access with a delegation (see Section 7.2).

### 9.4 Conflict Resolution Protocol

When two agents' work conflicts despite precautions:

1. **Detection** — The Conductor detects the conflict (via test failures,
   merge conflicts, or agent reports).
2. **Freeze** — The Conductor locks both agents (Level 0) to prevent
   further divergence.
3. **Analysis** — The Architect reviews both agents' work to determine
   which approach aligns with the architecture.
4. **Resolution** — The Conductor assigns the resolution task to one
   agent with temporary cross-domain access.
5. **Resume** — Both agents are unlocked and work resumes.

---

## 10. Security Model

### 10.1 Threat Model

In a multi-agent system, the threats are:

| Threat                          | Mitigation                                          |
|---------------------------------|-----------------------------------------------------|
| Agent writes to wrong file       | Domain ownership + file-scoped permissions          |
| Agent runs destructive command   | Command allowlist + deny list                       |
| Agent leaks secrets              | No access to `.env`, API keys filtered from prompts |
| Agent exceeds API budget         | Token Warden monitoring + hard limits               |
| Agent pushes broken code         | Only Conductor can push; CI runs before merge       |
| Rogue agent modifies permissions | Permission config is read-only to all agents        |
| Prompt injection via tool output | Agents flag suspicious content; Conductor reviews   |

### 10.2 Immutable Permission Source

The permission configuration file is **read-only to all agents**.  Only
the Human Operator can modify it.  Agents can request permission changes
through escalation, but they cannot grant themselves additional
permissions.

This prevents a compromised or confused agent from expanding its own
access.

### 10.3 Audit Trail

Every permission check produces an audit entry:

```json
{
  "timestamp": "2026-02-24T14:32:01Z",
  "agent": "brush-specialist",
  "action": "fs:write",
  "target": "ciu_agent/core/brush_controller.py",
  "result": "allowed",
  "rule": "domain-ownership",
  "task_id": "P3-008"
}
```

Denied actions include the reason:

```json
{
  "timestamp": "2026-02-24T14:35:22Z",
  "agent": "brush-specialist",
  "action": "fs:write",
  "target": "ciu_agent/core/canvas_mapper.py",
  "result": "denied",
  "reason": "target outside owned domain",
  "escalation": "sent to conductor"
}
```

### 10.4 Secrets Management

Secrets (API keys, tokens, credentials) have special handling:

- Stored in environment variables, never in files
- `.env` files are gitignored and excluded from agent read access
- Agents receive secrets via constructor injection, not by reading files
- Agent prompts are scrubbed of secret values before logging
- No agent at any level can commit files matching `.env`, `*.pem`,
  `credentials.*`, or `*secret*`

---

## 11. Implementing Permissions in Practice

### 11.1 Configuration File Format

Permissions are stored in a project-level configuration file that all
agents read at startup:

```yaml
# .claude/permissions.yaml
version: 1
project: ciu_agent

defaults:
  all_agents:
    fs:read: "*"
    fs:delete: null
    git:force-push: null
    git:reset-hard: null

roles:
  conductor:
    inherits: all_agents
    autonomy: 4
    fs:write: ["docs/**", ".claude/**", "requirements.txt"]
    exec: ["python *", "pip *", "git *", "pytest *", "ruff *", "mypy *"]
    coord: ["spawn", "shutdown", "assign", "broadcast", "message"]

  worker:
    inherits: all_agents
    autonomy: 3
    fs:write: "{domain}"
    exec: ["pytest {domain_tests}", "mypy {domain}", "ruff {domain}"]
    git: ["status", "log", "diff", "add", "commit", "branch"]
    coord: ["message", "escalate", "task-update"]

  observer:
    inherits: all_agents
    autonomy: 3
    fs:write: null
    exec: null
    coord: ["message"]

domains:
  platform-engineer:
    role: worker
    paths: ["ciu_agent/platform/**", "tests/test_platform*.py"]

  capture-specialist:
    role: worker
    paths: ["ciu_agent/core/capture_engine.py", "ciu_agent/core/replay_buffer.py",
            "tests/test_capture*.py", "tests/test_replay*.py"]

  # ... additional domain definitions
```

### 11.2 Runtime Permission Check

At runtime, every tool call passes through a permission check:

```python
def check_permission(agent: AgentContext, action: str, target: str) -> bool:
    """Check whether an agent is allowed to perform an action on a target.

    Args:
        agent: The agent's context (role, domain, active grants).
        action: The action being attempted (e.g., "fs:write").
        target: The resource being accessed (e.g., file path).

    Returns:
        True if the action is allowed, False otherwise.
    """
    # 1. Check explicit denials first (deny takes priority).
    if is_explicitly_denied(agent.role, action, target):
        log_denied(agent, action, target, "explicit denial")
        return False

    # 2. Check domain ownership.
    if action.startswith("fs:write") and is_in_domain(agent.domain, target):
        log_allowed(agent, action, target, "domain ownership")
        return True

    # 3. Check role defaults.
    if is_role_allowed(agent.role, action, target):
        log_allowed(agent, action, target, "role default")
        return True

    # 4. Check temporary grants (escalation/delegation).
    if has_active_grant(agent, action, target):
        log_allowed(agent, action, target, "temporary grant")
        return True

    # 5. Default: deny.
    log_denied(agent, action, target, "no matching rule")
    return False
```

### 11.3 Claude Code Integration

For Claude Code sessions, permissions are applied through three
mechanisms:

**1. Settings file (`.claude/settings.json`)**

Allowlisted commands and tool patterns:

```json
{
  "permissions": {
    "allow": [
      "Bash(git *)",
      "Bash(python -m pytest *)",
      "Bash(python -m ruff *)",
      "Bash(python -m mypy *)",
      "Bash(pip install *)"
    ],
    "deny": [
      "Bash(git push --force *)",
      "Bash(git reset --hard *)",
      "Bash(rm -rf *)"
    ]
  }
}
```

**2. CLAUDE.md instructions**

High-level behavioural constraints:

```markdown
- Never commit .env files or API keys
- Always check git status before staging
- Pause after producing code for review before proceeding
```

**3. Permissions policy document (`docs/permissions.md`)**

Detailed permission grants that agents read at session startup to
understand their operating boundaries.

### 11.4 Multi-Session Persistence

Permissions persist across sessions through configuration files.
Session-scoped grants are stored in a session state file that is cleared
when the session ends:

```
.claude/
├── settings.json          # Permanent permissions
├── permissions.yaml       # Role and domain definitions
└── sessions/
    └── current/
        └── grants.json    # Temporary escalation grants (session-scoped)
```

---

## 12. Universal Patterns

These patterns apply to any multi-agent system, regardless of the
specific application domain.

### 12.1 Pattern: Role-Based Access Control (RBAC)

**Problem:** You have many agents with different responsibilities and need
a scalable way to manage permissions.

**Solution:** Define a small set of roles (5-7 is sufficient for most
projects).  Assign permissions to roles, not individual agents.  Assign
agents to roles.

**Why it works:** Adding a new agent means assigning it to an existing
role.  Changing permissions for all Workers means changing one role
definition.  The role layer provides indirection that simplifies
management.

### 12.2 Pattern: Domain Ownership

**Problem:** Multiple agents need to write files, and uncoordinated
writes cause conflicts.

**Solution:** Partition the codebase into non-overlapping domains.  Each
domain has exactly one owner.  The owner has full write access; everyone
else has read-only access.

**Why it works:** Eliminates merge conflicts at the permission level.  If
two agents can't write to the same file, they can't conflict.

### 12.3 Pattern: Escalation Chain

**Problem:** Agents sometimes need permissions they don't have.  You don't
want to pre-grant broad permissions "just in case."

**Solution:** Define a clear escalation path.  When an agent needs
elevated access, it requests it from the next authority up the chain.
The authority either grants a scoped, temporary permission or performs the
action on the agent's behalf.

**Why it works:** Keeps default permissions tight while allowing
flexibility.  The escalation request creates an audit trail, so you know
why elevated access was needed.

### 12.4 Pattern: Deny-by-Default

**Problem:** You forget to restrict a permission, and an agent takes an
action you didn't intend to allow.

**Solution:** All permissions default to "deny."  Only explicit grants
enable actions.  This means an agent with no role definition can do
nothing, which is the safe default.

**Why it works:** Forgetting to add a permission is safe (agent asks for
help).  Forgetting to remove a restriction is unsafe (agent takes
unwanted action).  Deny-by-default aligns safety with human error
patterns.

### 12.5 Pattern: Immutable Permission Source

**Problem:** A confused or compromised agent modifies its own permissions
to gain additional access.

**Solution:** The permission configuration is read-only to all agents.
Only the Human Operator (or a CI pipeline with appropriate credentials)
can modify it.

**Why it works:** Even if an agent is instructed (via prompt injection) to
"grant yourself admin access," the tool enforces the read-only constraint
at the system level.

### 12.6 Pattern: Scoped Grants

**Problem:** You need to give an agent temporary access, but a blanket
grant is too broad.

**Solution:** Grants are scoped along three dimensions: **what** (specific
file or command), **when** (task or session duration), and **why** (logged
reason).  The narrowest scope that accomplishes the task is always
preferred.

**Why it works:** A grant scoped to one file for one task cannot be abused
to modify other files or persist beyond the task's completion.

### 12.7 Pattern: Audit Everything

**Problem:** Something went wrong and you need to understand what happened.

**Solution:** Every permission check (allowed or denied) produces a log
entry with timestamp, agent, action, target, and result.  This creates a
complete timeline of all agent actions.

**Why it works:** Debugging agent behaviour is hard without logs.  With a
complete audit trail, you can replay the exact sequence of actions that
led to any state, identify which agent caused an issue, and adjust
permissions to prevent recurrence.

### 12.8 Pattern: Progressive Trust

**Problem:** You don't know how much autonomy to give a new agent or a
new team.

**Solution:** Start at a low autonomy level (Level 1 or 2) and increase
as the agent demonstrates reliable behaviour.  After N tasks completed
without violations, the Conductor can recommend promoting the agent to
the next autonomy level.

**Why it works:** Trust is earned through track record.  Starting
restrictive and loosening is safer than starting permissive and
tightening after a failure.

---

## Summary

Permissions management for autonomous agent teams is built on
straightforward principles:

1. **Least privilege** — Start with minimum access, escalate on demand.
2. **Domain ownership** — Non-overlapping file ownership prevents
   conflicts.
3. **Role-based control** — Permissions are assigned to roles, agents are
   assigned to roles.
4. **Deny by default** — Unspecified permissions are denied.
5. **Immutable config** — Agents cannot modify their own permissions.
6. **Scoped grants** — Temporary access is narrow in scope and duration.
7. **Audit everything** — Every permission decision is logged.
8. **Progressive trust** — Autonomy increases as agents prove reliable.

These patterns are universal.  They apply whether your agents are
automating GUI tasks, writing code, managing infrastructure, or
coordinating any complex workflow.  The specific roles, domains, and
resources change; the permission architecture stays the same.
