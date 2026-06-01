"""NB06 — Assembly Policies & Knowledge: real agent calls."""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from autogen.beta import Agent, KnowledgeConfig
from autogen.beta.compact import CompactTrigger, TailWindowCompact
from autogen.beta.config import OpenAIConfig
from autogen.beta.knowledge import MemoryKnowledgeStore
from autogen.beta.policies import ConversationPolicy, SlidingWindowPolicy

config = OpenAIConfig("gpt-5.4-mini", api_key=os.getenv("OPENAI_API_KEY"))


async def main():
    # --- Assembly policies ---
    agent = Agent(
        "demo",
        prompt="You are a helpful research assistant.",
        config=config,
        assembly=[
            ConversationPolicy(),
            SlidingWindowPolicy(max_events=40, transparent=True),
        ],
    )

    reply = await agent.ask("How does context management work in multi-agent research?")
    print("=== Assembly demo ===")
    print(reply.body[:500])

    # --- Knowledge config ---
    store = MemoryKnowledgeStore()

    knowledge = KnowledgeConfig(
        store=store,
        compact=TailWindowCompact(target=30),
        compact_trigger=CompactTrigger(max_events=50),
    )

    agent_with_knowledge = Agent(
        "researcher",
        prompt="You are a researcher with persistent memory.",
        config=config,
        knowledge=knowledge,
        assembly=[
            ConversationPolicy(),
            SlidingWindowPolicy(max_events=40, transparent=True),
        ],
    )

    print(f"\n=== Knowledge demo ===")
    print(f"Store before: {await store.list('/')}")

    reply = await agent_with_knowledge.ask("What do we know about chain-of-thought prompting?")
    print(f"Reply: {reply.body[:300]}")
    print(f"Store after: {await store.list('/')}")


asyncio.run(main())
