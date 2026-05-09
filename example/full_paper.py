"""Run research and save both paper + flow for replay."""

import asyncio
import json

from dotenv import load_dotenv

load_dotenv()


async def main():
    from lionag2 import ResearchEngine

    engine = ResearchEngine(
        model="gpt-5.4-mini",
        max_depth=1,
        novelty_threshold=0.85,
        paper_max_iterations=1,
        on_event=lambda e: print(f"  [{e.get('type')}]", flush=True),
    )
    paper = await engine.run("What are the failure modes of chain-of-thought prompting?")

    with open("output_paper.md", "w") as f:
        f.write(paper.as_markdown())
    print(
        f"\nPaper: output_paper.md ({len(paper.body_markdown)} chars, quality={paper.quality_score})"
    )

    flow_data = engine.flow.to_dict()
    with open("output_flow.json", "w") as f:
        json.dump(flow_data, f, default=str)
    print(f"Flow:  output_flow.json ({len(json.dumps(flow_data, default=str))} bytes)")
    print("\nReplay: python example/replay.py output_flow.json")
    print("Stats:  python example/replay.py output_flow.json --stats")


asyncio.run(main())
