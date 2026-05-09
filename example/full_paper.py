"""Run and save full paper."""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()

async def main():
    from lionag2 import ResearchEngine
    engine = ResearchEngine(
        model="gpt-5.4-mini", max_depth=1, novelty_threshold=0.85,
        paper_max_iterations=1,
        on_event=lambda e: print(f"  [{e.get('type')}]", flush=True),
    )
    paper = await engine.run("What are the failure modes of chain-of-thought prompting?")

    out = "output_paper.md"
    with open(out, "w") as f:
        f.write(paper.as_markdown())
    print(f"\nSaved to {out} ({len(paper.body_markdown)} chars, quality={paper.quality_score})")

asyncio.run(main())
