# Skill: Git Commit and Push

## Purpose

Reusable skill for committing and pushing code changes from the local repository to the remote GitHub repository. This skill handles staging, committing with descriptive messages, and pushing to the correct branch.

## Repository

- Local path: `D:\projects\ciu_agent`
- Remote: `https://github.com/MensuraMedia/ciu_agent`
- Authentication: Pre-configured (no credential prompts expected)

## When to Use

Use this skill after completing any unit of work that should be preserved:

- After creating or modifying files
- After completing a build phase or milestone
- After fixing bugs or issues
- After updating documentation
- When explicitly asked to commit/push

## Workflow

### Step 1: Check Status

```bash
cd D:\projects\ciu_agent
git status
```

Review what has changed. Identify untracked files, modified files, and deleted files.

### Step 2: Stage Changes

For all changes:

```bash
git add -A
```

For specific files only (when partial commits are needed):

```bash
git add path/to/file1 path/to/file2
```

### Step 3: Commit

Write a descriptive commit message. Follow conventional commit format:

```bash
git commit -m "type(scope): short description"
```

Commit types:

- `feat`: New feature or capability
- `fix`: Bug fix
- `docs`: Documentation changes only
- `refactor`: Code restructuring without behavior change
- `test`: Adding or updating tests
- `chore`: Maintenance tasks, dependency updates, config changes
- `build`: Build system or phase completion

Scope should match the component being changed: `capture`, `canvas`, `brush`, `director`, `platform`, `config`, `docs`.

Examples:

```
feat(capture): add cross-platform screen capture engine
docs(architecture): update canvas mapper specification
fix(brush): correct zone boundary detection at screen edges
build(phase1): complete foundation phase deliverables
chore(deps): add opencv and mss to requirements.txt
```

### Step 4: Push

```bash
git push origin main
```

If working on a feature branch:

```bash
git push origin <branch-name>
```

If the branch doesn't exist on remote yet:

```bash
git push -u origin <branch-name>
```

### Step 5: Verify

```bash
git log --oneline -3
```

Confirm the commit appears and the push succeeded.

## Branch Strategy

- `main`: Stable, working code. Push here after validation.
- `dev`: Active development. Default working branch.
- `feat/<name>`: Feature branches for isolated work.
- `fix/<name>`: Bug fix branches.

Create branches when:

- Starting a new build phase
- Working on experimental changes
- Making changes that might break existing functionality

```bash
git checkout -b feat/canvas-mapper
```

Merge back to dev when complete:

```bash
git checkout dev
git merge feat/canvas-mapper
git push origin dev
```

## Error Recovery

If push is rejected (remote has changes):

```bash
git pull --rebase origin main
git push origin main
```

If merge conflicts occur:

1. Report the conflict to the user
2. Do not auto-resolve without confirmation
3. Show the conflicting files and let the user decide

## Rules

- Never force push (`--force`) without explicit user permission
- Always check `git status` before staging
- Always use descriptive commit messages, never use generic messages like "update" or "changes"
- Never commit sensitive data (API keys, credentials, .env files)
- Always verify the push succeeded before moving on
