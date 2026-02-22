# CIU Agent — Permissions Policy

## Scope

This policy applies to all Claude Code sessions operating within the `D:\projects\ciu_agent` project directory. It grants full operational permissions for building, testing, and deploying the CIU Agent application system.

## Authorization

The operator (project owner) authorizes Claude Code and all spawned agents, sub-agents, and team members to perform the following actions without prompting for confirmation.

## File System Permissions

**Granted without prompting:**

- Create, read, edit, delete any file within `D:\projects\ciu_agent\`
- Create and remove directories within the project tree
- Move and rename files within the project tree
- Write to all subdirectories including `ciu_agent/`, `docs/`, `tests/`, `skills/`, `sessions/`, `.claude/`

**Not permitted:**

- Access or modify files outside `D:\projects\ciu_agent\`
- Access or modify system files
- Access or modify other project directories

## Shell and Command Permissions

**Granted without prompting:**

```
# Python
python *
python -m pytest *
python -m mypy *
python -m ruff *
python -m pip install *
pip install *
pip install -r requirements.txt

# Git
git add *
git commit *
git push *
git pull *
git checkout *
git branch *
git merge *
git status
git log *
git diff *
git stash *
git rebase *
git tag *
git remote *
git fetch *

# Package management
pip install --upgrade *
pip uninstall -y *
pip freeze
pip list

# Build and test
pytest *
ruff check *
ruff format *
mypy *

# File operations
mkdir *
rmdir *
del *
copy *
move *
ren *
type *
dir *
tree *

# Utilities
echo *
cd *
cls
where *
```

**Not permitted:**

- `format` (disk format)
- `shutdown`, `restart`
- `reg` (registry edits)
- `netsh`, `net` (network configuration)
- `sfc`, `dism` (system file operations)
- Any command that modifies system-level configuration
- Any command that accesses network resources outside of `github.com/MensuraMedia/ciu_agent`

## Git Permissions

**Granted without prompting:**

- Stage all changes (`git add -A`)
- Commit with descriptive messages following conventional commit format
- Push to `origin` (https://github.com/MensuraMedia/ciu_agent)
- Create, switch, and delete local branches
- Merge branches
- Pull and rebase from remote
- Tag releases

**Not permitted:**

- Force push (`git push --force`) — requires explicit confirmation
- Push to any remote other than `origin`
- Modify `.gitignore` to include sensitive files
- Commit files matching `.gitignore` patterns

## API Permissions

**Granted without prompting:**

- Make Claude API calls for Tier 2 canvas analysis
- Make Claude API calls for Director task planning
- Make API calls for testing and validation during development

**Constraints:**

- Log all API calls with timestamp, token count, and purpose
- Do not send any credentials, API keys, or personal data in prompts
- Respect rate limits with backoff

## Agent and Team Permissions

**Granted without prompting:**

- Conductor may spawn any agent defined in `docs/agents.md`
- Agents may spawn their own sub-agents as defined
- Agents may communicate via shared task board and mailbox
- Agents may read any file in the project tree
- Agents may write to files within their owned directories (see `docs/agents.md`)
- Test Engineer may run any test command
- All agents may use the git skill after completing work

**Constraints:**

- Maximum 5 concurrent agents
- Sub-agents report to parent agent only
- Cross-domain file writes require Architect agent review (logged, not blocked)

## Installation Permissions

**Granted without prompting:**

- Install Python packages via pip
- Install npm packages if needed for tooling
- Create virtual environments
- Update `requirements.txt` with new dependencies

**Not permitted:**

- Install system-level packages (apt, choco, brew)
- Modify system PATH
- Install services or daemons
- Modify Windows registry

## Decision-Making Permissions

**Granted without prompting:**

- Choose implementation patterns within established architecture
- Select appropriate data structures and algorithms
- Write and run tests
- Refactor code for clarity or performance
- Fix bugs and resolve test failures
- Update documentation to reflect changes
- Create new files and modules as needed by the architecture

**Requires human confirmation:**

- Changes to the architecture document (`docs/architecture.md`) that alter component interfaces
- Adding new external dependencies not already in `requirements.txt`
- Deleting files that are tracked in git
- Any action that would be irreversible

## Session Behavior

- Start each session by reading `CLAUDE.md`
- Check `docs/phases.md` and `docs/taskboard.json` for current state
- Proceed with work without asking "should I continue?" or "is this okay?"
- Report results after completion, not before starting
- If blocked by an ambiguity not covered by docs, make the pragmatic choice and document it
- If a decision could go multiple ways with equal merit, pick one, proceed, and note the alternative in a code comment

## Override

The project owner may override any permission in this document at any time during a session by stating the override in chat. Overrides apply only to the current session unless the owner requests a permanent change to this document.

## How to Apply

In Claude Code, run:

```
/permissions
```

Then allowlist the following patterns:

```
Bash(git *)
Bash(python *)
Bash(pip *)
Bash(pytest *)
Bash(ruff *)
Bash(mypy *)
Bash(mkdir *)
Bash(move *)
Bash(copy *)
Bash(del *)
Bash(dir *)
Bash(tree *)
Bash(echo *)
Bash(cd *)
Bash(type *)
```

Or apply all at once by pointing Claude Code to this file:

```
Read docs/permissions.md and apply the granted permissions for this session.
Proceed with full autonomy on all tasks within the project scope.
Do not prompt for confirmation on routine operations.
```
