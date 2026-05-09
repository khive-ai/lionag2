"""Minimal test — single agent with knowledge + assembly, same config as engine."""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()


async def main():
    from autogen.beta import Agent, KnowledgeConfig
    from autogen.beta.compact import CompactTrigger, TailWindowCompact
    from autogen.beta.config import OpenAIConfig
    from autogen.beta.knowledge import MemoryKnowledgeStore
    from autogen.beta.policies import ConversationPolicy
    from autogen.beta.tools import ExaToolkit

    from lionag2.core import SafeSlidingWindowPolicy
    from lionag2.research.tools import EMISSION_TOOLS

    config = OpenAIConfig("gpt-5.4-mini", api_key=os.getenv("OPENAI_API_KEY"))

    agent = Agent(
        "surveyor",
        prompt="You are a research surveyor. Search for sources, cite them.",
        config=config,
        tools=list(ExaToolkit().tools) + EMISSION_TOOLS,
        knowledge=KnowledgeConfig(
            store=MemoryKnowledgeStore(),
            compact=TailWindowCompact(target=30),
            compact_trigger=CompactTrigger(max_events=50),
        ),
        assembly=[
            ConversationPolicy(),
            SafeSlidingWindowPolicy(max_events=40, transparent=True),
        ],
    )
    print(f"Agent tools: {[t.name for t in agent.tools]}")

    reply = await agent.ask(
        "Find 3 papers about chain-of-thought prompting failures. "
        "For each, cite title and one key finding."
    )
    print(f"\nReply ({len(reply.body)} chars):\n{reply.body[:800]}")


asyncio.run(main())
