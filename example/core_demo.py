"""Demo of core primitives — Pile, Progression, Flow — with AG2 events."""

from autogen.beta.events import BaseEvent, Field

from lionag2 import Flow, Pile

# -- Define some event types --------------------------------------------------


class Finding(BaseEvent):
    claim: str = Field(kw_only=False)
    novelty: float = Field(default=0.5)
    source: str = "unknown"
    depth: int = 0


class DepthRequest(BaseEvent):
    question: str = Field(kw_only=False)
    parent_depth: int = 0


class Contradiction(BaseEvent):
    claim_a: str = Field(kw_only=False)
    claim_b: str = Field(default="", kw_only=False)


# -- Pile demo ----------------------------------------------------------------

print("=== Pile ===\n")

pile = Pile()
f1 = Finding("spin fluctuations dominate pairing", novelty=0.9, source="theorist", depth=0)
f2 = Finding("phonon contribution is weak", novelty=0.3, source="analyst", depth=1)
f3 = Finding("magnetic resonance tracks Tc", novelty=0.85, source="surveyor", depth=1)
d1 = DepthRequest("what is the pairing glue?", parent_depth=0)
c1 = Contradiction("AFM glue at all dopings", "AFM only at optimal doping")

pile.include([f1, f2, f3, d1, c1])
print(f"Pile: {pile}")
print(f"f1.lion_id = {f1.lion_id}")
print()

# By type
print(f"pile[Finding]:       {len(pile[Finding])} items")
print(f"pile[DepthRequest]:  {len(pile[DepthRequest])} items")
print(f"pile[Contradiction]: {len(pile[Contradiction])} items")
print()

# AG2 Condition DSL
high_novelty = pile[Finding.novelty > 0.7]
print(f"Finding.novelty > 0.7: {[f.claim[:30] for f in high_novelty]}")

depth_1 = pile[Finding.depth == 1]
print(f"Finding.depth == 1:    {[f.claim[:30] for f in depth_1]}")
print()

# By index
print(f"pile[0]:  {pile[0]}")
print(f"pile[-1]: {pile[-1]}")
print(f"pile[-2:]: {pile[-2:]}")
print()

# Evict
removed = pile.evict(lambda e: isinstance(e, Finding) and e.novelty < 0.5)
print(f"Evicted {len(removed)} low-novelty findings, {len(pile)} remaining")

# -- Flow demo ----------------------------------------------------------------

print("\n=== Flow ===\n")

flow = Flow(name="research")

# Include events into specific progressions (streams)
flow.include([f1, f3], progressions=["surveyor"])
flow.include([f1, f2], progressions=["analyst"])  # f1 in BOTH — object vs reference
flow.include([d1, c1], progressions=["bus"])

print(f"Flow: {flow}")
print(f'flow["surveyor"]: {len(flow["surveyor"])} events')
print(f'flow["analyst"]:  {len(flow["analyst"])} events')
print(f'flow["bus"]:      {len(flow["bus"])} events')
print()

# f1 is in surveyor AND analyst — same object, two references
print(f"f1 in surveyor: {f1 in [e for e in flow['surveyor']]}")
print(f"f1 in analyst:  {f1 in [e for e in flow['analyst']]}")
print(f"Total unique items: {len(flow.items)}")
print()

# Auto-routed stream
flow.new_stream(Finding.novelty > 0.7, name="high_novelty")
print(f'flow["high_novelty"]: {len(flow["high_novelty"])} events (backfilled)')

# New finding auto-routes
f4 = Finding("new breakthrough", novelty=0.95, source="innovator")
flow.include(f4, progressions=["innovator"])
print(f'After adding f4: flow["high_novelty"] = {len(flow["high_novelty"])} events')
print()

# Type access across all streams
print(f"flow.items[Finding]:       {len(flow.items[Finding])} total")
print(f"flow.items[DepthRequest]:  {len(flow.items[DepthRequest])}")
print(f"flow.items[Contradiction]: {len(flow.items[Contradiction])}")

# -- Persistence --------------------------------------------------------------

print("\n=== Persistence ===\n")

import json

data = flow.to_dict()
serialized = json.dumps(data, default=str)
print(f"Serialized: {len(serialized):,} bytes")

flow2 = Flow.from_dict(json.loads(serialized))
print(f"Reconstructed: {flow2}")
print(f"Findings preserved: {len(flow2.items[Finding])}")
print(f"Progressions preserved: {flow2.progression_names}")

# IDs round-trip
orig_ids = [str(e.lion_id) for e in flow.items]
new_ids = [str(e.lion_id) for e in flow2.items]
print(f"IDs match: {orig_ids == new_ids}")
