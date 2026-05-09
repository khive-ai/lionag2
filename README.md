# lionag2

**Pile/Progression/Flow primitives + recursive multi-agent research on AG2 beta.**

## What it is

Two things in one package:

1. **`lionag2.core`** — portable data structures for AG2 event streams: ID-keyed ordered collections (Pile), ordered sequences (Progression), and shared multi-stream state (Flow). Thread-safe, async-safe, AG2 Condition DSL compatible.

2. **`lionag2.research`** — a recursive research engine where 7 specialized agents investigate a question, spawn sub-investigations on novel findings, cross-check for contradictions, and produce a structured paper with quality scoring. Built entirely on AG2 beta primitives + the core module.

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
```

### Core primitives

```python
from lionag2 import Pile, Flow
from autogen.beta.events import BaseEvent, Field

class Finding(BaseEvent):
    claim: str = Field(kw_only=False)
    novelty: float = Field(default=0.5)

# Pile — ID-keyed, ordered, type-indexed
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

# Save
data = engine.flow.to_dict()
json.dump(data, open("run.json", "w"), default=str)

# Reconstruct — polymorphic, IDs preserved
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
                          │
                          ▼
               ┌────────────────────┐
               │   ResearchEngine   │
               │   (Flow-native)    │
               └────────┬───────────┘
                        │
    ┌───────────────────┼───────────────────┐
    ▼                   ▼                   ▼
  Root team        Child team          Child team
  (7 agents)       (depth+1)          (depth+1)
    │                   │                   │
    └───────────────────┴───────────────────┘
                        │
              All events in Flow.items (Pile)
              Each stream = a Progression view
                        │
                ┌───────┴───────┐
                ▼               ▼
          Cross-check     Paper loop
          (structured)    (iterative)
                │               │
                └───────┬───────┘
                        ▼
                   PaperDraft
              (quality scored)
```

### Default agent roster

| Agent | Tools | Role |
|---|---|---|
| **Surveyor** | search, fetch, memory, graph, messages | Literature scout — broad coverage, alternative framings |
| **DataDigger** | search, fetch, memory, graph | Dataset hunter — real datasets, benchmarks |
| **Theorist** | search, fetch, memory | Mechanism formalizer — equations, assumptions |
| **Analyst** | search, fetch, run_code, memory, graph | Quantitative analyst — real code on real data |
| **Innovator** | search, fetch, memory, graph | Alternative hypothesis generator |
| **Critic** | search, fetch, memory, graph, messages | Adversarial reviewer — stress-test + structured summary |
| **Connector** | memory, graph | Knowledge graph weaver (khive only) |

### Reactive coordination

The research tree emerges from event flow, not imperative loops:

```
FindingEmitted(novelty=0.9)
  → EventWatch fires
  → DepthRequested emitted to bus
  → EventWatch fires
  → child team spawns at depth+1

PaperGapEvent(priority="high")
  → EventWatch fires
  → DepthRequested
  → child fills the gap
  → paper rewrites with new evidence
```

### Flow — the state layer

All coordination state lives in the Flow as typed events:

| Event | Replaces | Purpose |
|---|---|---|
| `NodeRegistered` | `_node_depths` dict | Node metadata with stream name |
| `TopicSeen` | `_seen_topics` set | Deduplication |
| `UrlCaptured` | `title_to_url` dict | Citation grounding |
| `AgentTurnDone` | log messages | Agent execution trace |
| `PaperDrafted` | inline state | Paper quality tracking |
| `ExplorationComplete` | return value only | Final stats |

This means the entire execution is replayable from `flow.to_dict()`.

## Core module

### Pile

Thread-safe (RLock), async-safe (asyncio.Lock), ID-keyed ordered collection. Every item gets a UUID `lion_id` on inclusion. Supports AG2's Condition DSL as `__getitem__` keys:

```python
pile[SomeType]                        # by type
pile[SomeType.field > value]          # AG2 OpCondition
pile[TypeA | TypeB]                   # AG2 OrCondition (via _ConditionMeta)
pile[lambda e: ...]                   # predicate
pile[uuid]                            # by ID
pile[0], pile[-3:]                    # by index/slice
pile.evict(predicate)                 # active context management
pile.by_type(TypeA, TypeB)            # multi-type lookup
```

### Progression

Ordered deque of UUIDs with O(1) membership. Decoupled from storage — multiple Progressions can reference the same Pile items (object vs reference).

### Flow

Shared `items: Pile` + named streams. Each stream is a `MemoryStream` backed by `FlowStorage` — an AG2 `Storage` protocol adapter that writes to the shared pile and a named progression.

```python
flow = Flow()
flow.streams["agent_a"]              # MemoryStream (pass to agent.ask)
flow.streams["bus"]                   # coordination bus
flow.items[SomeType]                  # all events of type
flow["agent_a"]                       # events in agent_a's progression order
flow.new_stream(condition, name=...)  # auto-routed materialized view
flow.evict(pred, progressions=["a"]) # remove from one view, keep in pile
flow.to_dict() / Flow.from_dict()    # polymorphic persist/reconstruct
```

### SafeSlidingWindowPolicy

Drop-in replacement for AG2's `SlidingWindowPolicy`. Ensures tool call/result pairing across the entire assembled context, not just the leading edge.

```python
from lionag2.core import SafeSlidingWindowPolicy

agent = Agent("x", ..., assembly=[
    ConversationPolicy(),
    SafeSlidingWindowPolicy(max_events=40, transparent=True),
])
```

## Server

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
# Direct research run
lionag2 "What causes LLM hallucinations?" --max-depth 2 --model gpt-5.4-mini
```

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `model` | `gpt-5.4-mini` | Model for all agents (1M context) |
| `max_depth` | 3 | Maximum recursion depth |
| `novelty_threshold` | 0.7 | Minimum novelty to spawn a child |
| `paper_max_iterations` | 2 | Max paper rewrite cycles |
| `paper_quality_threshold` | 0.7 | Quality score to accept paper |
| `khive_api_key` | env | Optional khive for persistent knowledge |
| `on_event` | None | SSE callback for live progress |

## Environment

```bash
OPENAI_API_KEY=sk-...              # Required
EXA_API_KEY=...                    # For search (optional but recommended)
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
│   ├── prompts.py                  # 7 specialist prompts
│   ├── tools.py                    # 4 emission tools
│   ├── middleware.py               # HTML cleaning for Exa
│   ├── server.py                   # ag-ui + SSE server
│   └── cli.py                      # CLI entry
├── notebooks/                      # 12-part tutorial series
└── example/                        # minimal.py, full_paper.py, replay.py
```

## Notebooks

12-part tutorial building up from AG2 basics to the full engine:

| # | Topic |
|---|-------|
| 01 | Getting started — Agent + Exa + observer pattern |
| 02 | Typed events & structured output |
| 03 | Tool middleware (HTML cleaning) |
| 04 | Stream architecture (bus + bridges) |
| 05 | Reactive watches (EventWatch, CadenceWatch) |
| 06 | Assembly policies & knowledge |
| 07 | Specialist roster & depth-aware prompts |
| 08 | khive integration (KnowledgeStore, Toolkit) |
| 09 | Cross-check & iterative paper loop |
| 10 | Recursive depth expansion |
| 11 | ag-ui server |
| 12 | Capstone — full engine end-to-end |

## Built on

- [AG2](https://github.com/ag2ai/ag2) (beta) — agents, streams, watches, tools, knowledge
- [Exa](https://exa.ai) — neural search
- [Daytona](https://daytona.io) — code execution sandbox
- [khive](https://khive.ai) — persistent memory, knowledge graph, communication
