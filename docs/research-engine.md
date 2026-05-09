# Research Engine

The research engine runs a team of 7 specialized agents that investigate a question recursively, cross-check findings, and produce a structured paper.

## How it works

```
topic → root team (7 agents) → findings with novelty scores
                                   │
                              novelty > threshold?
                              ├── yes → DepthRequested → child team at depth+1
                              └── no  → done
                                   │
                         (reactive: watches on event bus)
                                   │
                              all teams settle
                                   │
                              cross-check → contradictions, gaps
                                   │
                              paper loop → PaperDraft(quality_score)
                                   │
                              gaps → DepthRequested → fill → rewrite
                                   │
                              quality ≥ threshold → done
```

## Flow-native state

All coordination state lives in `flow.items` as typed events:

```python
engine = ResearchEngine(model="gpt-5.4-mini", max_depth=2)
paper = await engine.run("What causes LLM hallucinations?")

# Query the execution trace
engine.flow.items[FindingEmitted]       # all research findings
engine.flow.items[NodeRegistered]       # all exploration nodes
engine.flow.items[AgentTurnDone]        # agent execution log
engine.flow.items[UrlCaptured]          # all captured URLs
engine.flow.items[TopicSeen]            # dedup log
engine.flow.items[PaperDrafted]         # paper iteration history
```

## Event types

### Research events (emitted by agents via tools)

| Event | Fields | Purpose |
|---|---|---|
| `FindingEmitted` | claim, evidence, novelty, confidence, source_agent, depth | Source-backed claim |
| `DepthRequested` | question, novelty, parent_node_id, parent_depth | Spawn child investigation |
| `ContradictionFound` | claim_a, claim_b, source_a, source_b, severity | Conflicting claims |
| `PivotDetected` | description, source_agent | Hypothesis contradiction |
| `PaperGapEvent` | section, description, research_question, priority | Gap needing research |

### Engine coordination events

| Event | Fields | Purpose |
|---|---|---|
| `NodeRegistered` | node_id, topic, depth, parent_node_id, stream_name | Node created |
| `TeamStarted` | node_id, agents, depth | Team roster |
| `AgentTurnStarted` | node_id, agent | Agent begins (transient) |
| `AgentTurnDone` | node_id, agent, chars | Agent completed |
| `AgentTurnError` | node_id, agent, error | Agent failed |
| `TopicSeen` | normalized, node_id | Dedup record |
| `UrlCaptured` | title, url | Search result URL (transient) |
| `CrossCheckDone` | contradictions, gaps | Cross-check results |
| `PaperDrafted` | iteration, quality, gaps | Paper iteration |
| `ExplorationComplete` | total_nodes, total_findings, max_depth, paper_quality | Final stats |

## Reactive watches

Three watches on the bus stream drive the research tree:

```python
EventWatch(FindingEmitted)   → _on_finding     # high novelty → DepthRequested
EventWatch(DepthRequested)   → _on_depth_request # spawn child team
EventWatch(PaperGapEvent)    → _on_paper_gap    # gap → DepthRequested
```

## Auto-routed streams

The engine creates condition-based streams at startup:

```python
flow.new_stream(FindingEmitted, name="findings")
flow.new_stream(FindingEmitted.novelty > threshold, name="high_novelty")
```

Any `FindingEmitted` included into the pile (from any agent's stream) auto-appears in the "findings" progression.

## Persistence & replay

```python
# Save
data = engine.flow.to_dict()
json.dump(data, open("run.json", "w"), default=str)

# Replay
python example/replay.py run.json
python example/replay.py run.json --stats
python example/replay.py run.json -t FindingEmitted --min-novelty 0.7
python example/replay.py run.json -p bus
```

## SSE callback

```python
def on_event(event: dict) -> None:
    # event["type"] = class name (e.g., "FindingEmitted", "AgentTurnDone")
    # All other fields from the event
    print(f"[{event['type']}] {event}")

engine = ResearchEngine(on_event=on_event, ...)
```

## Khive integration

When `KHIVE_API_KEY` is set:
- `KhiveKnowledgeStore` replaces `MemoryKnowledgeStore` — AG2's knowledge harness runs on khive
- `KhiveToolkit` provides memory/graph/communication tools to agents
- `Connector` agent joins the roster — weaves discoveries into the knowledge graph
- Each research run compounds — future recall gets better

Without khive, the engine uses in-memory storage and the Connector is skipped.
