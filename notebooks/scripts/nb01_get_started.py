"""NB01 — Getting Started: Agent + Exa + Observer."""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from autogen.beta import Agent, MemoryStream
from autogen.beta.config import OpenAIConfig
from autogen.beta.events import ModelRequest, ModelResponse, ToolCallEvent, ToolResultsEvent
from autogen.beta.tools import ExaToolkit

config = OpenAIConfig("gpt-5.4-mini", api_key=os.getenv("OPENAI_API_KEY"))
exa = ExaToolkit(api_key=os.getenv("EXA_API_KEY"))

title_to_url: dict[str, str] = {}

agent = Agent(
    "surveyor",
    prompt="You are a research surveyor. Search broadly, cite real sources.",
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
                    title_to_url[t] = u


async def main():
    stream = MemoryStream()
    reply = await agent.ask(
        "Find 5 recent papers on reactive event-driven multi-agent coordination. "
        "For each, give title, year, and one key finding.",
        stream=stream,
    )
    print("=== Agent Reply ===")
    print(reply.body)

    print(f"\n=== {len(title_to_url)} URLs captured by observer ===")
    for title, url in title_to_url.items():
        print(f"  [{title}]({url})")

    print("\n=== Stream Events ===")
    from collections import Counter

    events = await stream.history.get_events()
    counts = Counter(type(e).__name__ for e in events)
    print(f"Total: {len(events)}")
    for name, count in counts.most_common():
        print(f"  {name}: {count}")


asyncio.run(main())
