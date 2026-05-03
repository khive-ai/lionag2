# lionag2

**Recursive self-exploratory multi-agent research.**

## What it is

A research engine where a team of 6 specialized agents (Surveyor → DataDigger →
Theorist → Analyst → Innovator → Critic) investigates a question, then **spawns
sub-investigations on its own open questions**, recursively, until you hit a
configured depth limit.

The agents don't just summarize search results — they fetch and read pages,
formalize the underlying mechanism, run real Python on real datasets to test
predictions, propose alternative hypotheses, and produce a final structured
research paper (markdown → LaTeX → PDF) with self-correction and a quality score.

## What it solves

Most "AI research" demos return a Wikipedia-style summary of search snippets.
That's not research — it's auto-complete. lionag2 forces the system to:

- **Read the actual sources** (`fetch_url`), not just snippets.
- **Verify claims with code** on real datasets, not toy random simulations.
- **Build a shared knowledge graph** (entities + links) so parallel branches
  reuse what siblings discovered.
- **Cross-team-message** when one branch contradicts another.
- **Self-correct** the synthesis by fact-checking the draft against the evidence.
- **Score the result** with structured quality metrics (citation count, evidence
  quality, novelty, completeness, verdict).
- **Go deeper, not broader, on recursion** — the depth-aware prompt explicitly
  shifts goals from "map the territory" to "drill the mechanism" to "empirical
  specifics" as depth increases.

## How it works

```
            Research question
                  │
                  ▼
        ┌─────────────────┐
        │  Root team      │  Surveyor → DataDigger → Theorist → Analyst → Innovator → Critic
        │  (6 agents)     │  ↓ tools: tavily, fetch_url, run_code, khive memory/graph/comm
        └─────┬───────────┘
              │ open questions with novelty ≥ 0.7 spawn child nodes
              ▼
       ┌──────┴──────┐
       │             │
   child team    child team   ← parallel, depth+1 = deeper not broader
       │             │
       └──────┬──────┘
              ▼
      cross-section correction (LLM, structured CrossCheckReport)
              ▼
      paper synthesis (markdown, with math + code outputs + 30+ citations)
              ▼
      self-correction pass (structured SelfCorrectionReport)
              ▼
      markdown → LaTeX → PDF
              ▼
      quality eval (structured QualityMetrics)
```

All steps stream live over SSE. The frontend renders the exploration tree, the
per-agent conversation with tool calls and outputs, and a research-process report
with all source URLs and stats.

It is built on:

- **AG2** (AutoGen) — multi-agent GroupChat with tool calling and handoff conditions
- **lionagi** — provider-agnostic LLM orchestration, structured output, hooks, sandboxes
- **khive** — persistent memory, graph (entities + links), cross-team communication
- **OpenRouter** routing to **Google Gemini** for the agents
- **Tavily** for web search

---

## Why "recursive" and not a static DAG?

A typical multi-agent research pipeline plans the teams up front and runs them
to completion: one DAG, one report. That's fine when you already know the
shape of the question.

`lionag2` instead lets the agents **decide what to investigate next based on
what they just discovered**. Each exploration node:

1. Runs a multi-agent team (Surveyor → Analyst → Critic by default).
2. Produces structured findings, code outputs, citations, and **open questions**
   — each scored for novelty.
3. Any open question with high enough novelty spawns a child exploration node
   at the next depth, with the parent's findings injected as context.
4. The tree expands breadth-first up to `max_depth`.

This means surprising results lead to more exploration, while obvious /
already-covered questions get pruned. The exploration is shaped by what the
agents actually find, not by an upfront plan.

---

## Architecture

```
                 ┌─────────────────────────────────────────────┐
                 │  ExplorationTree (root topic, max_depth)    │
                 └─────────────────────────────────────────────┘
                                       │
                  ┌────────────────────┼────────────────────┐
                  ▼                    ▼                    ▼
            Node d=0:topic       Node d=1:Q1          Node d=1:Q2
            ┌───────────┐       ┌───────────┐        ┌───────────┐
            │  TEAM     │       │  TEAM     │        │  TEAM     │
            │ Surveyor  │       │ Surveyor  │        │ Surveyor  │
            │ Analyst   │       │ Analyst   │        │ Analyst   │
            │ Critic    │       │ Critic    │        │ Critic    │
            └─────┬─────┘       └─────┬─────┘        └─────┬─────┘
                  │                   │                    │
              tools fire ──── shared knowledge bus ────────┘
                              memory + graph + comm
                                      │
                                      ▼
                           ┌────────────────────┐
                           │ cross-section      │
                           │ correction (LLM)   │
                           └─────────┬──────────┘
                                     ▼
                           ┌────────────────────┐
                           │ paper synthesis    │
                           └─────────┬──────────┘
                                     ▼
                           ┌────────────────────┐
                           │ self-correction    │
                           │ pass               │
                           └─────────┬──────────┘
                                     ▼
                           ┌────────────────────┐
                           │ markdown → LaTeX   │
                           │ → PDF              │
                           └─────────┬──────────┘
                                     ▼
                           ┌────────────────────┐
                           │ quality eval       │
                           │ (structured score) │
                           └────────────────────┘
```

### Default agent roster

| Agent | Tools | Job |
|---|---|---|
| **Surveyor** | `tavily_search`, `memory_recall`, `graph_search`, `list_messages` | Find 8-12 academic sources, list with TITLE / AUTHORS / YEAR / URL / contribution |
| **Analyst** | `run_code`, `tavily_search`, `memory_recall`, `memory_remember`, `graph_add_entity`, `graph_add_link` | Pick a quantitative claim, write real Python (numpy/scipy/pandas/sklearn), execute it, build the knowledge graph |
| **Critic** | `tavily_search`, `memory_recall`, `graph_neighbors`, `send_message` | Stress-test the weakest claim, escalate contradictions to other branches via cross-team messages, produce the final structured summary |

The agent roster is fully configurable per request — POST a custom `agents` list
to `/api/explore` to swap roles, tools, or system prompts.

### Shared knowledge

All teams across all branches share three communication channels:

1. **`memory`** (semantic memory) — store / recall facts via natural language queries.
2. **`graph`** (knowledge graph) — add typed entities (papers, methods, concepts)
   and typed links (`cites`, `extends`, `contradicts`, `uses_method`, ...). Other
   teams can `graph_search` and `graph_neighbors` to navigate it.
3. **`communication`** (cross-team messaging) — when Critic in branch A finds a
   contradiction with branch B's findings, it can `send_message(to_team='branch_B', ...)`
   so B sees the flag at the start of its next turn.

This is what makes parallel branches more than just "the same agent run N times".

### Verification protocol

A claim is more credible when:

- A real citation can be retrieved by tavily.
- A code block produced a numerical result consistent with the claim.
- Another branch independently corroborated it.
- Critic's stress-test could not knock it down.

Each `Finding` carries a `confidence` score (0-1). The cross-section correction
pass (after all branches finish) and the self-correction pass (after paper
synthesis) explicitly hunt for unsupported numbers and fabricated citations.

### Quality evaluation

The final pass produces a structured `QualityMetrics` record:

```python
class QualityMetrics(BaseModel):
    citation_count: int
    novelty_score: float          # 0..1
    evidence_quality: float        # 0..1
    contradiction_count: int
    correction_count: int
    coverage_score: float          # 0..1
    paper_completeness: float      # 0..1
    verdict: str                   # "publishable" | "needs work" | "insufficient"
```

---

## Running it

### Environment

```bash
# .env at repo root
OPENROUTER_API_KEY=sk-or-v1-...        # Gemini via OpenRouter
GEMINI_API_KEY=sk-or-v1-...            # alias of OPENROUTER_API_KEY
TAVILY_API_KEY=tvly-...                # web search
KHIVE_API_KEY=sk-khive-...             # khive memory + graph + communication
KHIVE_BASE_URL=https://khive-mcp.fly.dev
```

### Server

```bash
cd /path/to/lionag2
uv run python scripts/agui_server.py
# → http://localhost:8765
```

### Trigger an exploration

```bash
curl -N -X POST http://localhost:8765/api/explore \
  -H 'Content-Type: application/json' \
  -d '{
    "topic": "Does multi-agent debate improve LLM factual accuracy?",
    "max_depth": 2,
    "max_concurrent": 2
  }'
```

The response is an SSE stream. Event types include:

| Event | Payload |
|---|---|
| `tree_init` | `root_id`, `topic`, `max_depth` |
| `node_active` | `node_id`, `topic`, `depth` |
| `team_active` | `node_id`, `agents` (with name, role, tools) |
| `agent_message` | `node_id`, `agent`, `content` (per turn) |
| `tool_call` | `node_id`, `agent`, `tool`, `args` |
| `tool_result` | `node_id`, `agent`, `output` |
| `speaker_change` | `node_id`, `info` |
| `finding` | `node_id`, `claim`, `evidence` |
| `code_start` / `code_result` | `node_id`, `code`, `output`, `exit_code` |
| `child_spawned` | `parent_id`, `child_id`, `question`, `novelty_score`, `depth` |
| `node_pruned` | `node_id`, `question`, `reason` |
| `node_complete` | `node_id`, `finding_count`, `children_count` |
| `cross_check` | `corrections` (full text) |
| `synthesis` | `text` (full paper) |
| `self_correct` | `revised`, `original_length`, `revised_length` |
| `pdf_ready` | `path` |
| `quality_eval` | `metrics` (QualityMetrics) |
| `exploration_done` | `total_nodes`, `total_findings`, `max_depth_reached`, `pdf_path` |

### Custom agent roster

```jsonc
POST /api/explore
{
  "topic": "...",
  "max_depth": 2,
  "agents": [
    {
      "name": "DataDigger",
      "role": "Dataset hunter",
      "tools": ["tavily_search", "graph_add_entity"],
      "system_prompt": "Find datasets relevant to the topic. Add each as a graph entity. Hand off when done."
    },
    { "name": "Modeler",  "role": "...", "tools": ["run_code", "memory_remember"], "system_prompt": "..." },
    { "name": "Critic",   "role": "...", "tools": ["tavily_search", "memory_recall", "send_message"], "system_prompt": "..." }
  ]
}
```

The first agent in the list is the entry point. Each non-terminal agent's
`after_work` is mechanically chained to the next agent so the pipeline
always reaches the terminal critic, even if LLM-condition handoffs don't fire.

---

## What you get out

- **PDF**: `src/data/papers/{slug}.pdf` — full paper compiled from markdown via LaTeX.
- **Synthesis text**: streamed in the `synthesis` event (raw markdown).
- **Self-corrected version**: streamed in the `self_correct` event.
- **Quality score**: streamed in the `quality_eval` event.
- **Exploration tree**: every node, every finding, every code block, every spawned
  child available in the SSE stream for visualization.

---

## Files

```
src/lionag2/
  explore.py          # the recursive engine — NodeStatus, ExplorationTree, run_exploration,
                      # explore_node, _run_team_exploration, _cross_check, _write_paper,
                      # _self_correct, _generate_pdf, _evaluate_quality
  agent_tools.py      # the tool registry — tavily, run_code, memory, graph, communication
  models.py           # ResearchPlan / TeamSpec / TeamResult (legacy static-DAG path)
  flow.py, plan.py, execute.py  # legacy static-DAG entry points (kept for back-compat)
scripts/
  agui_server.py      # FastAPI SSE server — /api/explore, /api/explore/config, ...
  test_ag2_openrouter.py  # standalone debug script for AG2 + OpenRouter
frontend/
  src/                # React + Vite + Tailwind UI showing the exploration tree
```
