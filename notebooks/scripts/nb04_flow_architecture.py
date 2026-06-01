"""NB04 — Flow Architecture (no API keys needed)."""
import json

from lionag2.core import Flow
from lionag2.research.events import FindingEmitted

flow = Flow(name="research")

# Named streams are created on access
team_a = flow.streams["team_d0_abc123"]
team_b = flow.streams["team_d1_def456"]

print(f"Flow: {flow}")
print(f"Streams: {flow.progression_names}")
print(f"Shared pile: {flow.items}")

# Add a finding
finding = FindingEmitted(
    claim="Cuprate Tc peaks at 16% hole doping",
    evidence="Phase diagram data",
    source_agent="surveyor",
    novelty=0.8,
    depth=0,
)
flow.items.include(finding)

print(f"\nFlow items: {len(flow.items)}")
print(f"Findings: {len(flow.items.by_type(FindingEmitted))}")
if flow.items.by_type(FindingEmitted):
    print(f"  claim: {flow.items.by_type(FindingEmitted)[0].claim}")

# Query by progression
all_findings = flow.items.by_type(FindingEmitted)
print(f"\nAll findings: {len(all_findings)}")

for name in flow.progression_names:
    events = flow[name]
    print(f"  {name}: {len(events)} events")

# Serialization round-trip
data = flow.to_dict()
print(f"\nSerialized: {len(json.dumps(data, default=str))} bytes")

restored = Flow.from_dict(data)
print(f"Restored: {len(restored.items)} items, {len(restored.progression_names)} streams")
