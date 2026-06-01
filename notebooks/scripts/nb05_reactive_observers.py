"""NB05 — Reactive Observers: real agent with Exa, observer captures URLs."""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from autogen.beta import Agent, MemoryStream
from autogen.beta.config import OpenAIConfig
from autogen.beta.events import ToolResultsEvent
from autogen.beta.tools import ExaToolkit

config = OpenAIConfig("gpt-5.4-mini", api_key=os.getenv("OPENAI_API_KEY"))
exa = ExaToolkit(api_key=os.getenv("EXA_API_KEY"))

captured_urls: dict[str, str] = {}

agent = Agent(
    "surveyor",
    prompt="Search for papers and summarize findings.",
    config=config,
    tools=[exa],
)


@agent.observer(ToolResultsEvent)
def capture_urls(event: ToolResultsEvent) -> None:
    for r in event.results:
        result = getattr(r, "result", None)
        if not result:
            continue
        for part in getattr(result, "parts", []):
            data = getattr(part, "data", None)
            if not data:
                continue
            for hit in getattr(data, "results", None) or []:
                t, u = getattr(hit, "title", None), getattr(hit, "url", None)
                if t and u:
                    captured_urls[t] = u


async def main():
    stream = MemoryStream()
    reply = await agent.ask(
        "Find 3 papers on reactive multi-agent coordination. Give title and one key finding.",
        stream=stream,
    )

    print("=== Agent Reply ===")
    print(reply.body[:500])

    print(f"\n=== URLs captured by observer: {len(captured_urls)} ===")
    for title, url in list(captured_urls.items())[:5]:
        print(f"  [{title[:60]}]({url})")

    # Event stats
    events = await stream.history.get_events()
    from collections import Counter

    counts = Counter(type(e).__name__ for e in events)
    print(f"\n=== Events in stream: {len(events)} ===")
    for name, count in counts.most_common():
        print(f"  {name}: {count}")

    print(f"\nThe observer fired {len(captured_urls)} times during the agent's turn.")


asyncio.run(main())
