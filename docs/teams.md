# CIU Agent — Teams

## Team Structure

Agents are organized into teams based on build phases. Not all agents are active at all times. Teams are assembled for each phase and disbanded when the phase completes.

## Team Configurations

### Team: Foundation (Phase 1)

```
Conductor (team lead)
├── Architect
├── Platform Engineer
│   ├── platform:linux-impl
│   ├── platform:windows-impl
│   └── platform:macos-impl
├── Capture Specialist
│   ├── capture:frame-differ
│   └── capture:recorder
├── Test Engineer
│   └── test:unit-writer
└── Documentation
```

Focus: Get screen capture and cursor tracking working on all platforms.

### Team: Canvas (Phase 2)

```
Conductor (team lead)
├── Architect
├── Canvas Specialist
│   ├── canvas:zone-detector
│   ├── canvas:api-analyst
│   └── canvas:registry-manager
├── Capture Specialist (support role — provides frame stream)
├── Test Engineer
│   ├── test:unit-writer
│   └── test:mock-builder
└── Documentation
```

Focus: Zone segmentation, registry, and tiered analysis.

### Team: Brush (Phase 3)

```
Conductor (team lead)
├── Architect
├── Brush Specialist
│   ├── brush:motion-planner
│   └── brush:event-emitter
├── Canvas Specialist (support role — provides zone data)
├── Platform Engineer (support role — input injection)
├── Test Engineer
│   ├── test:unit-writer
│   └── test:integration-writer
└── Documentation
```

Focus: Cursor tracking, spatial events, motion planning, action execution.

### Team: Director (Phase 4)

```
Conductor (team lead)
├── Architect
├── Director Specialist
│   ├── director:task-planner
│   ├── director:error-handler
│   └── director:verifier
├── Brush Specialist (support role — executes actions)
├── Canvas Specialist (support role — provides zone data)
├── Test Engineer
│   ├── test:integration-writer
│   └── test:mock-builder
└── Documentation
```

Focus: Task decomposition, execution loop, error recovery.

### Team: Integration (Phase 5)

```
Conductor (team lead)
├── Architect (elevated role — final design review)
├── All Specialists (support roles)
├── Test Engineer
│   ├── test:unit-writer
│   ├── test:integration-writer
│   └── test:mock-builder
└── Documentation
    ├── docs:api-documenter
    └── docs:changelog-writer
```

Focus: End-to-end testing, cross-platform validation, performance tuning, documentation.

## Team Communication Rules

### Within a Team

- Agents communicate through the shared task board
- Direct messages via the mailbox system for urgent coordination
- Support-role agents respond to queries from the primary agents but don't initiate work

### Between Phases

- Each phase produces a "handoff document" listing:
  - What was built
  - What interfaces are available for the next phase
  - Known issues or limitations
  - Test coverage status
- The Conductor archives the task board and starts a fresh one

### Escalation Path

```
Sub-agent → Parent Agent → Conductor → Architect
```

- Sub-agents escalate to their parent agent first
- Parent agents escalate to the Conductor if the issue is cross-domain
- The Conductor escalates to the Architect if the issue is architectural

## Team Spawning with Claude Code

To enable agent teams in Claude Code, set the experimental flag:

```json
// .claude/settings.json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

Then instruct the Conductor to assemble the team:

```
I'm working on the CIU Agent project, Phase 1 (Foundation).

Read CLAUDE.md, docs/conductor.md, docs/teams.md, and docs/phases.md.

Assemble the Foundation team. Break Phase 1 into tasks,
populate the task board, and begin assigning work.
Use agent teams for parallel execution where tasks are independent.
```

## Resource Constraints

- Maximum 5 concurrent agents (context + API cost management)
- Opus model reserved for: Architect, Canvas Specialist (Tier 2), Director Specialist
- Sonnet model for all other agents
- Support-role agents share context with their team lead, not separate sessions
- Sub-agents run within their parent agent's session unless the task requires isolation

## When to Use Teams vs Single Agent

Use a team when:

- Multiple independent files need to be created in parallel
- Different domains need to contribute to the same phase
- Verification needs to happen independently of implementation

Use a single agent when:

- Work is sequential with tight dependencies
- Changes touch a single file or closely related files
- Quick fixes or small updates
