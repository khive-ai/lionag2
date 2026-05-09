import argparse
import asyncio
import json

from .engine import ResearchEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Recursive AG2-beta research.")
    parser.add_argument("topic", help="Research question")
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--max-concurrent", type=int, default=4)
    parser.add_argument("--json-events", action="store_true")
    args = parser.parse_args()

    def on_event(event: dict) -> None:
        if args.json_events:
            print(json.dumps(event, default=str), flush=True)
        else:
            kind = event.get("type")
            if kind in {
                "tree_init",
                "node_active",
                "child_spawned",
                "node_complete",
                "exploration_done",
                "paper_iteration",
                "paper_accepted",
            }:
                print(f"[{kind}] {event}", flush=True)
            elif kind == "finding":
                print(f"[finding] {event.get('claim')}", flush=True)

    async def _run() -> None:
        engine = ResearchEngine(
            model=args.model,
            base_url=args.base_url,
            max_depth=args.max_depth,
            max_concurrent=args.max_concurrent,
            on_event=on_event,
        )
        paper = await engine.run(args.topic)
        print("\n" + paper.as_markdown())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
