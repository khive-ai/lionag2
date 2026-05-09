"""Smoke test — full engine, depth=1."""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()


async def main():
    from lionag2 import ResearchEngine

    def on_event(e):
        t = e.get("type", "?")
        detail = e.get("claim", e.get("agent", e.get("question", "")))
        if detail:
            print(f"  [{t}] {str(detail)[:80]}")
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
    paper = await engine.run(
        "What are the failure modes of chain-of-thought prompting?"
    )

    print(f"\n--- Done ---")
    print(f"Quality: {paper.quality_score}")
    print(f"Length: {len(paper.body_markdown)} chars")
    print(f"\n{paper.as_markdown()}")


asyncio.run(main())
