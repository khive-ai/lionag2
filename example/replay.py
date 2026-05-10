"""Replay a research run from a saved Flow.

Usage:
  # 1. Run research and save
  python example/full_paper.py          # produces output_flow.json

  # 2. Replay the execution trace
  python example/replay.py output_flow.json

  # 3. Replay with filters
  python example/replay.py output_flow.json --type FindingEmitted
  python example/replay.py output_flow.json --type FindingEmitted --min-novelty 0.7
  python example/replay.py output_flow.json --progression bus
"""

import argparse
import json
from datetime import datetime

from lionag2.core import Flow
from lionag2.research.events import (
    CrossCheckDone,
    DepthRequested,
    ExplorationComplete,
    FindingEmitted,
    NodeRegistered,
    PaperDrafted,
    PaperGapEvent,
    TeamStarted,
    TopicSeen,
    UrlCaptured,
)

ICONS = {
    "NodeRegistered": "🌱",
    "TeamStarted": "👥",
    "FindingEmitted": "💡",
    "DepthRequested": "  ↓",
    "TopicSeen": "  ✓",
    "UrlCaptured": "🔗",
    "CrossCheckDone": "🔍",
    "PaperDrafted": "📄",
    "PaperGapEvent": "  ⚠",
    "ExplorationComplete": "🏁",
}


def fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:12]


def render(event, t0: float) -> str:
    name = type(event).__name__
    icon = ICONS.get(name, "  ·")
    elapsed = f"+{event.created_at - t0:.1f}s"
    ts = fmt_time(event.created_at)

    if isinstance(event, NodeRegistered):
        return f"{icon} {ts} {elapsed:>8}  node={event.node_id} depth={event.depth} topic={event.topic!r}"
    if isinstance(event, TeamStarted):
        return f"{icon} {ts} {elapsed:>8}  node={event.node_id} agents=[{', '.join(event.agents)}]"
    if isinstance(event, FindingEmitted):
        return f"{icon} {ts} {elapsed:>8}  [{event.source_agent} d={event.depth}] novelty={event.novelty:.2f} — {event.claim}"
    if isinstance(event, DepthRequested):
        return f"{icon} {ts} {elapsed:>8}  depth={event.parent_depth + 1} — {event.question}"
    if isinstance(event, TopicSeen):
        return f"{icon} {ts} {elapsed:>8}  dedup: {event.normalized}"
    if isinstance(event, UrlCaptured):
        return f"{icon} {ts} {elapsed:>8}  {event.title[:50]} → {event.url[:60]}"
    if isinstance(event, CrossCheckDone):
        return f"{icon} {ts} {elapsed:>8}  contradictions={event.contradictions} gaps={event.gaps}"
    if isinstance(event, PaperDrafted):
        return f"{icon} {ts} {elapsed:>8}  iteration={event.iteration} quality={event.quality:.2f} gaps={event.gaps}"
    if isinstance(event, PaperGapEvent):
        return f"{icon} {ts} {elapsed:>8}  [{event.priority}] {event.section}: {event.description}"
    if isinstance(event, ExplorationComplete):
        return f"{icon} {ts} {elapsed:>8}  nodes={event.total_nodes} findings={event.total_findings} depth={event.max_depth} quality={event.paper_quality:.2f}"
    return f"  · {ts} {elapsed:>8}  {name}: {event}"


def main():
    parser = argparse.ArgumentParser(description="Replay a lionag2 research flow")
    parser.add_argument("flow_json", help="Path to saved flow JSON")
    parser.add_argument("--type", "-t", help="Filter by event type name")
    parser.add_argument("--progression", "-p", help="Replay a specific progression only")
    parser.add_argument("--min-novelty", type=float, help="Filter findings by min novelty")
    parser.add_argument("--stats", action="store_true", help="Show summary stats only")
    args = parser.parse_args()

    with open(args.flow_json) as f:
        data = json.load(f)

    flow = Flow.from_dict(data)

    if args.stats:
        print(f"Flow: {flow.name}")
        print(f"Total events: {len(flow.items)}")
        print("Type breakdown:")
        for tname, count in flow.items.type_counts.items():
            print(f"  {tname.rsplit('.', 1)[-1]}: {count}")
        print(f"Progressions: {flow.progression_names}")
        for pname in flow.progression_names:
            print(f"  {pname}: {len(flow[pname])} events")
        findings = flow.items.by_type(FindingEmitted)
        if findings:
            avg_novelty = sum(f.novelty for f in findings) / len(findings)
            print(f"Findings: {len(findings)} (avg novelty={avg_novelty:.2f})")
        nodes = flow.items.by_type(NodeRegistered)
        if nodes:
            print(f"Nodes: {len(nodes)} (max depth={max(n.depth for n in nodes)})")
        urls = flow.items.by_type(UrlCaptured)
        print(f"URLs captured: {len(urls)}")
        return

    if args.progression:
        events = flow[args.progression]
    else:
        events = sorted(flow.items, key=lambda e: e.created_at)

    if args.type:
        events = [e for e in events if type(e).__name__ == args.type]

    if args.min_novelty is not None:
        events = [
            e for e in events if isinstance(e, FindingEmitted) and e.novelty >= args.min_novelty
        ]

    if not events:
        print("No events match filters.")
        return

    t0 = events[0].created_at
    print(f"Replaying {len(events)} events from {flow.name or 'unnamed'} flow\n")

    for event in events:
        print(render(event, t0))

    print(f"\n--- {len(events)} events, {events[-1].created_at - t0:.1f}s total ---")


if __name__ == "__main__":
    main()
