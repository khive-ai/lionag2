"""Smoke test — full engine, depth=1, with flow summary."""

import asyncio

from dotenv import load_dotenv

load_dotenv()


async def main():
    from lionag2 import ResearchEngine
    from lionag2.research.events import FindingEmitted, NodeRegistered

    def on_event(e):
        t = e.get("type", "?")
        if t == "agent_start":
            return
        if t == "agent_done":
            print(f"  <- {e.get('agent')} ({e.get('chars', 0):,} chars)")
        elif t == "agent_error":
            print(f"  !! {e.get('agent')} ERR: {str(e.get('error', ''))[:60]}")
        elif t == "FindingEmitted":
            print(f"  ** novelty={e.get('novelty')} {str(e.get('claim', ''))[:60]}")
        elif t == "ExplorationComplete":
            print(
                f"  == nodes={e.get('total_nodes')} findings={e.get('total_findings')} q={e.get('paper_quality')}"
            )
        else:
            print(f"  [{t}]")

    engine = ResearchEngine(
        model="gpt-5.4-mini",
        max_depth=1,
        novelty_threshold=0.85,
        paper_max_iterations=1,
        on_event=on_event,
    )

    print("--- Starting research (depth=1) ---\n")
    paper = await engine.run("What are the failure modes of chain-of-thought prompting?")

    print("\n--- Results ---")
    print(f"Quality: {paper.quality_score:.2f}")
    print(f"Paper:   {len(paper.body_markdown):,} chars")
    print(f"Flow:    {engine.flow}")

    nodes = engine.flow.items.by_type(NodeRegistered)
    findings = engine.flow.items.by_type(FindingEmitted)
    print(f"Nodes:   {len(nodes)}")
    print(f"Findings:{len(findings)}")
    print(f"URLs:    {len(engine.urls)}")

    print(f"\n{paper.as_markdown()[:500]}...")


asyncio.run(main())
