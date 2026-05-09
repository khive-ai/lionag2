# Core Primitives

lionag2's `core/` module provides three data structures for managing AG2 event streams with ID-based access, ordering, and multi-stream coordination.

## Pile

Thread-safe, async-safe, ID-keyed ordered collection.

Every item included in a Pile gets a UUID (`lion_id`) stamped onto it. AG2's `BaseEvent` stores attributes in `__dict__` via `setattr`, so adding `lion_id` is safe and serializes through AG2's existing `__uuid__` handler.

```python
from lionag2 import Pile
from autogen.beta.events import BaseEvent, Field

class Finding(BaseEvent):
    claim: str = Field(kw_only=False)
    novelty: float = Field(default=0.5)

pile = Pile()
f = Finding("spin fluctuations dominate", novelty=0.9)
pile.include(f)

f.lion_id  # UUID('7723f290-...') — stamped on include
```

### Polymorphic `__getitem__`

Pile's `__getitem__` dispatches based on key type:

```python
pile[uuid]                    # → single item by UUID
pile[0]                       # → by index in insertion order
pile[-3:]                     # → last 3 items (slice)
pile[Finding]                 # → all items of type Finding
pile[Finding.novelty > 0.7]   # → AG2 Condition DSL (OpCondition)
pile[Finding | Depth]         # → AG2 OrCondition (via _ConditionMeta)
pile[lambda e: ...]           # → predicate filter
pile[progression]             # → items in progression's order
```

AG2's Condition DSL works because event classes use `_ConditionMeta` as metaclass. Field operators (`>`, `<`, `==`, etc.) return `OpCondition` objects, and class-level `|` returns `OrCondition`. Pile checks `isinstance(key, Condition)` to catch DSL expressions.

### Thread/async safety

Pile uses dual locks:
- `threading.RLock` — for sync operations (`@_sync` decorator)
- `asyncio.Lock` — for async operations (`@_async` decorator)

```python
# Sync — automatically locked
pile.include(event)
pile.exclude(event_id)
pile.evict(lambda e: e.depth < 1)

# Async — automatically locked
await pile.ainclude(event)
await pile.aexclude(event_id)
await pile.aevict(lambda e: e.depth < 1)
```

### Type index

Pile maintains a `_type_index: dict[str, list[UUID]]` for O(1) type lookup. `pile.type_counts` gives a summary:

```python
pile.type_counts
# {'lionag2.research.events.FindingEmitted': 4,
#  'lionag2.research.events.DepthRequested': 2}
```

## Progression

Ordered deque of UUIDs with O(1) membership via set.

```python
from lionag2 import Progression

prog = Progression(name="surveyor")
prog.append(uuid1)
prog.append(uuid2)
uuid1 in prog     # True — O(1) via set
prog[0]            # uuid1
prog[-1]           # uuid2
```

Progression is **not** independently thread-safe — it relies on Pile's locks when used inside a Pile or Flow.

### Object vs reference

The key design: Pile owns the objects, Progressions hold references (UUIDs). The same object can appear in multiple Progressions:

```python
pile.include(event)                     # object stored once
progression_a.append(event.lion_id)     # reference in A
progression_b.append(event.lion_id)     # same reference in B
```

This is how Flow implements multi-stream state — one Pile, many Progression views.

## Flow

Shared `items: Pile` + named streams backed by Progressions.

```python
from lionag2 import Flow

flow = Flow(name="research")

# Streams auto-create on access
await agent_a.ask("...", stream=flow.streams["surveyor"])
await agent_b.ask("...", stream=flow.streams["analyst"])

# All events, all streams
flow.items[Finding]                     # type lookup across all streams
flow.items[Finding.novelty > 0.7]       # condition DSL

# Per-stream view
flow["surveyor"]                        # events in surveyor's progression order
flow["analyst"]                         # events in analyst's progression order
```

### FlowStorage

Each stream's `MemoryStream` uses `FlowStorage` as its Storage backend. When AG2 saves an event to a stream, FlowStorage writes it to the shared Pile and appends the UUID to the stream's Progression.

```python
# This happens automatically inside MemoryStream:
# FlowStorage.save_event(event, context)
#   → flow.include(event, progressions=["surveyor"])
#   → event goes to pile, UUID goes to "surveyor" progression
```

### Auto-routed streams

`flow.new_stream(condition)` creates a stream whose Progression auto-populates when matching events are included:

```python
# Create a view for high-novelty findings
flow.new_stream(Finding.novelty > 0.7, name="high_novelty")

# Now any high-novelty Finding included via ANY stream also appears here
flow.include(Finding("novel claim", novelty=0.9), progressions=["surveyor"])
# → auto-routed to "high_novelty" progression too
```

Existing matching items are backfilled on creation.

### Context management

```python
# Remove references from one stream, keep in pile
flow.evict(
    lambda e: e.depth < 1,
    progressions=["surveyor"],     # only affects surveyor's view
)
# event still in pile, other streams still see it

# Remove from pile entirely
flow.evict(lambda e: isinstance(e, ToolResultsEvent))
# gone from pile + all progressions
```

### Persistence

```python
# Serialize — polymorphic via AG2's __event__ + __uuid__ handlers
data = flow.to_dict()
# {
#   "name": "research",
#   "items": [{"__event__": "lionag2.research.events.FindingEmitted", ...}, ...],
#   "progressions": {"surveyor": ["uuid1", "uuid2"], "bus": ["uuid1", "uuid3"]}
# }

# Reconstruct — types restored, IDs preserved
flow2 = Flow.from_dict(data)
flow2.items[FindingEmitted]    # correct types, correct UUIDs
```

## SafeSlidingWindowPolicy

Drop-in replacement for AG2's `SlidingWindowPolicy`. Ensures tool call/result pairing across the entire assembled context:

```python
from lionag2.core import SafeSlidingWindowPolicy

agent = Agent("x", assembly=[
    ConversationPolicy(),
    SafeSlidingWindowPolicy(max_events=40, transparent=True),
])
```

AG2's built-in policy only strips orphaned `ToolResultsEvent` at the head of the window. `SafeSlidingWindowPolicy` scans the full list, matching every `ToolResultsEvent.results[].parent_id` against known `ToolCallsEvent.calls[].id`.

## Why `lion_id` not `id`

AG2's `ToolCallEvent` already has an `.id` attribute — it's the OpenAI tool call ID (e.g., `"call_abc123"`), not a UUID. Stamping a UUID onto `.id` would overwrite it and break AG2's internal tool call tracking.

`lion_id` is a separate namespace that coexists with any existing `.id`. AG2's serializer picks it up (it iterates `__dict__`) and handles it via the `__uuid__` codec.
