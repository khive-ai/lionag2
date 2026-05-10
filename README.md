# lionag2

**Pile/Progression/Flow primitives + recursive multi-agent research on AG2 beta.**

## What it is

Two things in one package:

1. **`lionag2.core`** — portable data structures for AG2 event streams: ID-keyed ordered collections (Pile), ordered sequences (Progression), and shared multi-stream state (Flow). Thread-safe, async-safe, AG2 Condition DSL compatible.

2. **`lionag2.research`** — a recursive research engine where specialized agents investigate a question, hand off to each other based on context, spawn sub-investigations on novel findings, and produce a structured paper. Built entirely on AG2 beta primitives + the core module.

## Install

```bash
pip install lionag2

# With server support
pip install "lionag2[server]"

# With khive persistent knowledge
pip install "lionag2[khive]"
```

## Quick start

### Research

```python
from lionag2 import ResearchEngine

engine = ResearchEngine(model="gpt-5.4-mini", max_depth=2)
paper = await engine.run("What causes hallucinations in large language models?")

print(paper.as_markdown())       # Full paper
print(paper.quality_score)       # 0-1 quality assessment
print(engine.flow)               # Flow(items=291, progressions=[...])

# Save everything
import json
json.dump(engine.flow.to_dict(), open("flow.json", "w"), default=str)
engine.save_conversations("conversations.md")
```

### Core primitives

```python
from lionag2 import Pile, Flow
from autogen.beta.events import BaseEvent, Field

class Finding(BaseEvent):
    claim: str = Field(kw_only=False)
    novelty: float = Field(default=0.5)

# Pile — ID-keyed, ordered, type-indexed, thread-safe
pile = Pile()
pile.include([Finding("spin fluctuations", novelty=0.9), Finding("phonon weak", novelty=0.3)])

pile[Finding]                         # all Findings
pile[Finding.novelty > 0.7]           # AG2 Condition DSL
pile[0]                               # by index
pile[some_uuid]                       # by ID

# Flow — shared pile + named streams
flow = Flow(name="research")
await agent.ask("...", stream=flow.streams["surveyor"])
await agent.ask("...", stream=flow.streams["analyst"])

flow.items[Finding]                   # all findings across all streams
flow["surveyor"]                      # events in surveyor's order
flow.new_stream(Finding.novelty > 0.7, name="high_novelty")  # auto-routed view
```

### Persistence & replay

```python
import json

# Save flow (events + progressions)
data = engine.flow.to_dict()
json.dump(data, open("run.json", "w"), default=str)

# Save full conversations (readable markdown)
engine.save_conversations("conversations.md")

# Programmatic access to conversations
convos = engine.export_conversations()
# → {"team_d0_abc_surveyor_0": [{"role": "user", ...}, {"role": "assistant", ...}], ...}

# Reconstruct flow — polymorphic, IDs preserved
flow = Flow.from_dict(json.load(open("run.json")))
flow.items[FindingEmitted]            # correct types restored
```

```bash
# Replay execution timeline
python example/replay.py run.json
python example/replay.py run.json --stats
python example/replay.py run.json -t FindingEmitted --min-novelty 0.7
```

## Architecture

```
                    Research question
                          |
                          v
               +--------------------+
               |   ResearchEngine   |
               |   (Flow-native)    |
               +---------+----------+
                         |
    +--------------------+--------------------+
    v                    v                    v
  Root team        Child team          Child team
  (6 agents)       (depth+1)          (depth+1)
    |                    |                    |
    +--------------------+--------------------+
                         |
              All events in Flow.items (Pile)
              Each stream = a Progression view
                         |
                +--------+--------+
                v                 v
          Cross-check       Paper loop
          (structured)      (iterative)
                |                 |
                +--------+--------+
                         v
                    PaperDraft
              (quality scored)
```

### Agent coordination

Agents within a team coordinate via **handoff**: each agent does its work, then calls `handoff("next_agent")` to route to the most relevant specialist, or `handoff("done")` to end the discussion. Default fallback is roster order.

Across depth levels, coordination is **reactive via observers**: when an agent emits a `FindingEmitted` with high novelty, an observer spawns a child team at depth+1 to investigate further.

### Default agent roster

Prompts adapt automatically based on available tools (khive, Exa search).

| Agent | Role |
|---|---|
| **Surveyor** | Literature scout — broad coverage, alternative framings |
| **DataDigger** | Dataset hunter — real datasets, benchmarks |
| **Theorist** | Mechanism formalizer — equations, assumptions |
| **Analyst** | Quantitative analyst — real code on real data |
| **Innovator** | Alternative hypothesis generator |
| **Critic** | Adversarial reviewer — stress-test claims |
| **Connector** | Knowledge graph weaver (khive only) |

### Reactive coordination

```
FindingEmitted(novelty=0.9)
  -> observer on agent fires
  -> _spawn_depth_node at depth+1
  -> child team runs concurrently

PaperGapEvent(priority="high")
  -> observer on paper writer fires
  -> depth expansion for gap
  -> paper rewrites with new evidence
```

### Flow — the state layer

All coordination state lives in the Flow as typed events:

| Event | Purpose |
|---|---|
| `NodeRegistered` | Node metadata with stream name |
| `TopicSeen` | Deduplication |
| `FindingEmitted` | Research claims with evidence, tagged by node_id |
| `DepthRequested` | Depth expansion trigger |
| `HandoffRequested` | Agent-to-agent routing |
| `UrlCaptured` | Citation grounding |
| `PaperGapEvent` | Paper quality gaps |
| `PaperDrafted` | Paper quality tracking |
| `ExplorationComplete` | Final stats |

The entire execution is replayable from `flow.to_dict()`. Full agent conversations are accessible via `engine.export_conversations()`.

## Core module

### Pile

Thread-safe (RLock), ID-keyed ordered collection. Every item gets a UUID `lion_id` on inclusion (not `.id` — avoids collision with AG2's ToolCallEvent.id). Supports AG2's Condition DSL as `__getitem__` keys:

```python
pile[SomeType]                        # by type
pile[SomeType.field > value]          # AG2 OpCondition
pile[TypeA | TypeB]                   # union type filter
pile[lambda e: ...]                   # predicate
pile[uuid]                            # by ID
pile[0], pile[-3:]                    # by index/slice
pile.by_type(TypeA, TypeB)            # multi-type lookup
```

### Progression

Ordered deque of UUIDs with O(1) membership. Decoupled from storage — multiple Progressions can reference the same Pile items (object vs reference).

### Flow

Shared `items: Pile` + named streams. Each stream is a `MemoryStream` backed by `FlowStorage` — an AG2 `Storage` protocol adapter that writes to the shared pile and a named progression.

Condition streams do not survive serialization (conditions are callables). Progression membership IS preserved.

```python
flow = Flow()
flow.streams["agent_a"]              # MemoryStream (pass to agent.ask)
flow.items[SomeType]                  # all events of type
flow["agent_a"]                       # events in agent_a's progression order
flow.new_stream(condition, name=...)  # auto-routed materialized view
flow.to_dict() / Flow.from_dict()    # polymorphic persist/reconstruct
```

### SafeSlidingWindowPolicy

Drop-in replacement for AG2's `SlidingWindowPolicy`. Filters orphaned tool results at the individual result level (not just keep/drop whole events).

```python
from lionag2.core import SafeSlidingWindowPolicy

agent = Agent("x", ..., assembly=[
    ConversationPolicy(),
    SafeSlidingWindowPolicy(max_events=40, transparent=True),
])
```

## Server

AG2 has native [ag-ui support](https://docs.ag2.ai/latest/docs/beta/ag-ui/) — lionag2's server builds on `AGUIStream` directly.

```bash
# ag-ui protocol (CopilotKit/Vercel AI SDK compatible)
lionag2-server --port 8000

# Endpoints
POST /              # ag-ui protocol
POST /api/research  # SSE stream of engine events
GET  /health        # service status
```

## CLI

```bash
lionag2 "What causes LLM hallucinations?" --max-depth 2 --model gpt-5.4-mini
```

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `model` | `gpt-5.4-mini` | Model for all agents (1M context) |
| `max_depth` | 3 | Maximum recursion depth |
| `max_concurrent` | 5 | Max concurrent depth nodes |
| `novelty_threshold` | 0.7 | Minimum novelty to spawn a child |
| `paper_max_iterations` | 2 | Max paper rewrite cycles |
| `paper_quality_threshold` | 0.7 | Quality score to accept paper |
| `khive_api_key` | env | Optional khive for persistent knowledge |
| `on_event` | None | SSE callback for live progress |

## Environment

```bash
OPENAI_API_KEY=sk-...              # Required
EXA_API_KEY=...                    # For search (recommended)
DAYTONA_API_KEY=...                # For code execution sandbox (optional)
KHIVE_API_KEY=...                  # For persistent knowledge graph (optional)
KHIVE_BASE_URL=https://...         # khive server URL
```

## Package structure

```
lionag2/
├── core/                           # Portable primitives
│   ├── pile.py                     # Pile — ID-keyed ordered collection
│   ├── progression.py              # Progression — ordered UUID deque
│   ├── flow.py                     # Flow — shared pile + named streams
│   ├── policies.py                 # SafeSlidingWindowPolicy
│   └── utils/                      # IDUtils, SyncUtils
├── tools/
│   └── khive_/                     # KhiveKnowledgeStore, KhiveToolkit
├── research/                       # Recursive research pipeline
│   ├── engine.py                   # Flow-native engine
│   ├── events.py                   # Research + coordination events
│   ├── models.py                   # PaperDraft, CrossCheckReport, etc.
│   ├── prompts.py                  # Specialist prompts (adapts to available tools)
│   ├── tools.py                    # Emission + handoff tools
│   ├── middleware.py               # HTML cleaning for Exa
│   ├── server.py                   # ag-ui + SSE server
│   └── cli.py                      # CLI entry
└── example/                        # full_paper.py, replay.py, smoke.py
```

## Built on

- [AG2](https://github.com/ag2ai/ag2) (beta) — agents, streams, tools, knowledge
- [Exa](https://exa.ai) — neural search
- [Daytona](https://daytona.io) — code execution sandbox
- [khive](https://khive.ai) — persistent memory, knowledge graph, communication
