# Token Budget and API Economics

> A comprehensive guide to managing API costs, latency, and reliability
> in autonomous agent systems — extracted from the CIU Agent but
> applicable to any LLM-powered automation.

---

## Table of Contents

1. [The Cost Model](#1-the-cost-model)
2. [Budget Architecture](#2-budget-architecture)
3. [Three-Tier Escalation Strategy](#3-three-tier-escalation-strategy)
4. [Token Optimization Strategies](#4-token-optimization-strategies)
5. [Timeout and Retry Economics](#5-timeout-and-retry-economics)
6. [Zone Preservation and Stale Data](#6-zone-preservation-and-stale-data)
7. [Adaptive Replanning Token Cost](#7-adaptive-replanning-token-cost)
8. [Monitoring and Observability](#8-monitoring-and-observability)
9. [Universal Token Budget Patterns](#9-universal-token-budget-patterns)
10. [Cost Projection Tables](#10-cost-projection-tables)

---

## 1. The Cost Model

### Three Costs of Every API Call

Every API call incurs three costs simultaneously:

| Cost Dimension | Metric | Impact |
|---------------|--------|--------|
| **Latency** | Wall-clock seconds | User waits; system blocked |
| **Tokens** | Input + output tokens | Direct monetary cost |
| **Reliability** | P(failure) per call | Wasted time + tokens on failures |

### CIU Agent Call Types

| Call Type | Purpose | Avg Latency | Avg Tokens | Failure Rate |
|-----------|---------|-------------|------------|--------------|
| **Tier 2 Vision** | Full-screen zone detection | 25-55s | ~4000 | ~10-15% |
| **Task Planning** | Decompose task into steps | 10-15s | ~2000 | ~5% |
| **Re-capture** | Update zones after UI change | 20-40s | ~4000 | ~10-15% |

### The Golden Rule

> **Minimize total API calls while maximizing task completion rate.**

Every call you eliminate saves latency, money, and reduces the chance of
a failure cascade. But every call you skip risks the agent acting on
stale information. The art is finding the optimal balance.

### Cost Per Task (Real-World Data)

From the CIU Agent "Open Notepad, type text, save" task:

```
Plan 1 (desktop → Start menu):   1 planning call
  Steps 1-3 executed:            0 calls (keyboard actions)
  Recaptures:                    3 calls (after each step)
  __replan__:                    1 recapture call

Plan 2 (Notepad → type → save):  1 planning call
  Steps 1-3 executed:            0 calls
  Recaptures:                    3 calls
  __replan__:                    1 recapture call

Plan 3 (Save dialog → complete): 1 planning call
  Steps 1-5 executed:            0 calls
  Recaptures:                    1 call
                                 ─────────
  TOTAL:                         11 API calls
  Duration:                      ~6 minutes
```

---

## 2. Budget Architecture

### Hard Ceiling: _MAX_API_CALLS

```python
# Maximum number of API calls per task to prevent runaway costs.
_MAX_API_CALLS: int = 30
```

This is a **hard ceiling** — when reached, the task immediately returns
with `error="API call budget exhausted"`. The budget covers ALL call
types: planning, recapture, re-analysis, and retries.

### Budget Allocation Formula

```
total_calls = initial_plan                     (1 call)
            + recaptures_per_transition × N    (N transitions)
            + replan_calls × M                 (M replans, 2 calls each)
            + retry_rate × total_steps         (failed step retries)
```

**Typical allocation for a 3-plan task:**

| Category | Calls | Notes |
|----------|-------|-------|
| Initial plan | 1 | First decomposition |
| Recaptures (plan 1) | 3 | After steps 1, 2, 3 |
| Replan 1 (recapture + plan) | 2 | __replan__ step |
| Recaptures (plan 2) | 3 | After steps 1, 2, 3 |
| Replan 2 (recapture + plan) | 2 | __replan__ step |
| Recaptures (plan 3) | 1 | After step 3 only |
| **Total** | **12** | 60% recapture, 27% planning, 13% replanning |

### Budget Exhaustion Strategy

When approaching the budget ceiling, the agent should:

1. **At 80%**: Log a warning, reduce recapture frequency
2. **At 90%**: Skip non-critical recaptures, continue execution
3. **At 100%**: Stop and report partial result with steps completed

---

## 3. Three-Tier Escalation Strategy

### Decision Tree

```
Frame captured
     │
     ▼
┌─────────────────────┐
│ Tier 0: Frame Diff  │  Cost: ~1ms, $0
│ Changed > 0.5%?     │
└────────┬────────────┘
         │
    No   │   Yes
    ▼    │    ▼
  SKIP   │  ┌──────────────────────┐
         │  │ Tier 1: OpenCV       │  Cost: ~50ms, $0
         │  │ Changed > 30%?       │
         │  └────────┬─────────────┘
         │           │
         │      No   │   Yes
         │      ▼    │    ▼
         │    LOCAL   │  ┌──────────────────┐
         │  ANALYSIS  │  │ Tier 2: Claude   │  Cost: ~30s, $$
         │           │  │ Full screen      │
         │           │  │ analysis         │
         │           │  └──────────────────┘
```

### The Lazy Evaluation Principle

> Don't call the API until you must.

- **Tier 0 runs on every frame** — it's essentially free (~1ms)
- **Tier 1 runs on ~5% of frames** — only when Tier 0 detects change
- **Tier 2 runs on ~0.1% of frames** — only on major transitions

### Recapture Heuristics

The Director uses keyword matching on `expected_change` to decide
whether to recapture after a step:

```python
triggers = (
    "window", "dialog", "open", "launch", "appear",
    "application", "notepad", "save as", "menu",
)
if any(keyword in change for keyword in triggers):
    self._recapture_fn()
```

This heuristic avoids recapturing after minor actions (typing a
character, pressing Tab) while catching major transitions (opening
an app, launching a dialog).

---

## 4. Token Optimization Strategies

### Strategy 1: Prompt Compression

The system prompt is the largest fixed cost per API call. Every token
in the system prompt is sent with every request.

| Optimization | Savings |
|-------------|---------|
| Remove verbose explanations | ~30% of system prompt tokens |
| Use abbreviations in examples | ~10% |
| Remove duplicate instructions | ~15% |

### Strategy 2: Zone Summarization

Send only essential zone fields:

```
Full zone:     id, label, type, state, bounds(x1,y1,x2,y2), confidence, parent_id, last_seen
Summarized:    id, label, type, state, center(cx,cy)
Savings:       ~40% fewer tokens per zone
```

### Strategy 3: Response Format

JSON arrays are token-efficient:

```json
[{"step_number":1,"zone_id":"btn_1","action_type":"click","parameters":{}}]
```

vs verbose descriptions:

```
Step 1: Click on the button labeled "Save" which is located at zone btn_1...
```

### Strategy 4: Model Selection

Use the cheapest model that can handle the task:

| Task | Recommended Model | Rationale |
|------|-------------------|-----------|
| Full screen analysis | Sonnet | Complex visual reasoning |
| Task planning | Sonnet | Structured JSON generation |
| Zone verification | Haiku | Simple yes/no comparison |
| Text extraction | Haiku | Simple reading task |

### Strategy 5: Caching

Don't re-analyze screens that haven't changed:

```python
# Before recapturing, check if screen actually changed
if frame_diff_percent < diff_threshold:
    return registry.count  # Keep existing zones, skip API call
```

---

## 5. Timeout and Retry Economics

### Timeout Costs

A timeout wastes:
- The full timeout duration of wall-clock time
- API tokens consumed by the server before timeout
- An API call slot from the budget

| Call Type | Timeout | Retry Cost |
|-----------|---------|-----------|
| Vision | 60s | 60s wasted + 1 budget slot |
| Text | 30s | 30s wasted + 1 budget slot |

### Exponential Backoff

```python
api_max_retries: int = 3
api_backoff_base_seconds: float = 2.0

# Retry delays: 2s → 4s → 8s
for attempt in range(retries):
    delay = backoff_base * (2 ** attempt)
    time.sleep(delay)
```

### The Retry Decision Tree

```
API call failed
     │
     ├── HTTP 500-599 (server error) → RETRY (transient)
     │
     ├── HTTP 400-499 (client error) → DON'T RETRY (our fault)
     │
     ├── Timeout → RETRY once (server may have been slow)
     │
     ├── Connection error → RETRY (network glitch)
     │
     └── Parse failure → DON'T RETRY (response was garbage)
         Keep existing zones instead.
```

### Parse Failure Economics

The CIU Agent experiences ~10-15% Tier 2 parse failure rate where
the API returns HTTP 200 but the response JSON is unparseable. These
are the most insidious failures because:

1. Full latency was consumed (25-55s)
2. Full tokens were consumed
3. No useful data was extracted

**Mitigation**: Keep existing zones on parse failure instead of wiping:

```python
if resp.success and not resp.zones:
    logger.warning("Re-capture returned 0 zones — keeping %d existing", registry.count)
    return registry.count  # Preserve stale-but-usable data
```

---

## 6. Zone Preservation and Stale Data

### The Most Recent Valid Strategy

The zone registry always holds the **most recent successful** zone set.
Failures never wipe the registry:

| Scenario | Action | Registry State |
|----------|--------|---------------|
| Re-capture succeeds, 35 zones | Replace all | 35 fresh zones |
| Re-capture succeeds, 0 zones (parse fail) | Keep existing | Previous zones preserved |
| Re-capture HTTP error | Keep existing | Previous zones preserved |
| Re-capture timeout | Keep existing | Previous zones preserved |

### Zone Expiry

Zones have a confidence that degrades over time:

```python
zone_expiry_seconds: float = 60.0  # Zones expire after 60s without refresh
```

After 60 seconds without a successful re-capture, zones are considered
stale and may be expired. But even stale zones are better than no zones
for planning purposes.

### The Staleness Trade-off

| Data Quality | Planning Quality | Risk |
|-------------|-----------------|------|
| Fresh zones (just captured) | Excellent | Low |
| Stale zones (10-30s old) | Good | Low — positions likely same |
| Very stale zones (30-60s old) | Moderate | Medium — some may have moved |
| No zones | Very poor | High — planner defaults to __global__ |

**The insight**: Even 30-second-old zones are dramatically better than
no zones at all. The planner can make visual-mode decisions with stale
data; with no data, it falls back to all-keyboard execution.

---

## 7. Adaptive Replanning Token Cost

### Fixed vs Adaptive Plans

| Approach | API Calls | Fragility | Completion Rate |
|----------|-----------|-----------|-----------------|
| Fixed plan (1 plan, all steps) | 1 | High — breaks on screen change | ~30% |
| Adaptive plan (N segments) | 1 + 2N | Low — fresh data each segment | ~85% |

### Cost Formula

```
adaptive_cost = initial_plan + Σ(recapture + replan) for each __replan__
             = 1 + 2 × num_replans

For a typical 3-segment task:
  1 + 2 × 2 = 5 planning-related calls
  + 6-10 recaptures between steps
  = 11-15 total calls
```

### Diminishing Returns

| Replans | Marginal Benefit | Cumulative Cost |
|---------|-----------------|-----------------|
| 0 (fixed plan) | Baseline | 1 call |
| 1 | +30% completion rate | 3 calls |
| 2 | +20% completion rate | 5 calls |
| 3 | +10% completion rate | 7 calls |
| 4 | +5% completion rate | 9 calls |
| 5+ | Diminishing | 11+ calls — likely stuck |

**Rule of thumb**: If you need more than 5 replans, the task is probably
stuck in a loop. The `_MAX_REPLANS = 5` ceiling prevents infinite loops.

---

## 8. Monitoring and Observability

### Structured Logging

Every API interaction is logged with quantitative data:

```
13:20:07 [INFO] Plan created: 4 steps (1 visual, 2 global, 1 replan), success=True
13:21:07 [INFO] Re-capture complete: 50 zones detected
13:21:56 [WARNING] Re-capture returned 0 zones (parse failure?) — keeping 50 existing zones
13:22:30 [INFO] Step 4: __replan__ — re-capturing screen and creating new plan
```

### Key Metrics to Track

| Metric | Formula | Target |
|--------|---------|--------|
| Calls per task | total API calls / completed tasks | < 15 |
| Cost per task | total tokens × price_per_token | < $0.05 |
| Success rate | succeeded tasks / total tasks | > 80% |
| Avg latency per call | total API time / total calls | < 35s |
| Parse failure rate | parse failures / total vision calls | < 10% |
| Recapture efficiency | useful recaptures / total recaptures | > 70% |
| Visual mode ratio | visual steps / total steps | > 30% |

### Budget Alerts

```python
# Log warnings as budget depletes
if self._api_calls_used >= _MAX_API_CALLS * 0.8:
    logger.warning(
        "API budget at %d%% (%d/%d calls used)",
        int(100 * self._api_calls_used / _MAX_API_CALLS),
        self._api_calls_used,
        _MAX_API_CALLS,
    )
```

---

## 9. Universal Token Budget Patterns

These patterns apply to ANY agent using LLM APIs:

### Web Scraping Agents

| Call Type | Equivalent |
|-----------|-----------|
| Tier 2 Vision | Full page extraction (expensive) |
| Tier 1 Local | CSS selector extraction (cheap) |
| Re-capture | Page reload after navigation |
| Replan | Different extraction strategy |

### Code Generation Agents

| Call Type | Equivalent |
|-----------|-----------|
| Full analysis | Analyze entire file (expensive) |
| Targeted analysis | Analyze single function (moderate) |
| Verification | Syntax check (free/local) |
| Replan | Different implementation approach |

### Conversational Agents

| Call Type | Equivalent |
|-----------|-----------|
| Full context | Send entire conversation history |
| Summarized context | Send summary + recent messages |
| RAG retrieval | Look up specific knowledge |
| Replan | Rephrase or change approach |

### Multi-Agent Systems

| Concern | Strategy |
|---------|----------|
| Coordinator overhead | Minimize coordinator API calls; use lightweight routing |
| Worker redundancy | Don't send same data to multiple workers |
| Shared budget | Pool budget across team, allocate per-task |
| Budget isolation | Cap per-agent budget to prevent one agent consuming all |

---

## 10. Cost Projection Tables

### Per-Task Cost Breakdown

Assuming Claude Sonnet pricing (~$3/M input, ~$15/M output tokens):

| Component | Avg Calls | Avg Tokens | Cost |
|-----------|-----------|------------|------|
| Initial Tier 2 | 1 | ~4000 | ~$0.015 |
| Task planning | 1 | ~2000 | ~$0.008 |
| Recaptures | 5 | ~20000 | ~$0.075 |
| Replanning | 2 | ~4000 | ~$0.015 |
| Retries (est.) | 1 | ~3000 | ~$0.012 |
| **Total per task** | **10** | **~33000** | **~$0.125** |

### Daily Cost Projections

| Usage Level | Tasks/Day | API Calls/Day | Est. Daily Cost |
|------------|-----------|---------------|-----------------|
| Light | 10 | 100 | ~$1.25 |
| Medium | 50 | 500 | ~$6.25 |
| Heavy | 200 | 2000 | ~$25.00 |

### Optimization Impact

| Optimization | Reduction | Savings/Day (Medium) |
|-------------|-----------|---------------------|
| Reduce recapture frequency | -30% calls | ~$1.88 |
| Use Haiku for verification | -40% per verification call | ~$0.50 |
| Cache unchanged screens | -20% calls | ~$1.25 |
| Compress system prompts | -15% tokens | ~$0.94 |
| **All optimizations** | | **~$4.57 (73% savings)** |

---

## Related Documents

- [AGENT_PHILOSOPHY.md](AGENT_PHILOSOPHY.md) — Core agent design principles
- [ADAPTIVE_REPLANNING.md](ADAPTIVE_REPLANNING.md) — Replanning architecture
- [DEVELOPMENT_PATTERNS.md](DEVELOPMENT_PATTERNS.md) — Code patterns
- [architecture.md](architecture.md) — CIU Agent system architecture
