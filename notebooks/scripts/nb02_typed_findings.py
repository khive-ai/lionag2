"""NB02 — Typed Events & Structured Output."""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from autogen.beta import Agent, PromptedSchema
from autogen.beta.config import OpenAIConfig

from lionag2.research.events import FindingEmitted
from lionag2.research.models import CrossCheckReport
from lionag2.research.tools import EMISSION_TOOLS

config = OpenAIConfig("gpt-5.4-mini", api_key=os.getenv("OPENAI_API_KEY"))

# --- Event types ---
f = FindingEmitted(
    claim="Spin-fluctuation pairing dominates near optimal doping",
    evidence="INS shows resonance at ~5*kB*Tc",
    source_agent="theorist",
    novelty=0.85,
    confidence=0.7,
    depth=0,
)
print(f"FindingEmitted: claim={f.claim!r}, novelty={f.novelty}, depth={f.depth}")

# --- Emission tools ---
print("\nEmission tools:")
for t in EMISSION_TOOLS:
    print(f"  {t.name}: {t.schema.function.description[:60]}")

# --- Structured output with PromptedSchema ---
async def main():
    checker = Agent(
        "cross_checker",
        prompt="Cross-check these findings for contradictions and gaps.",
        config=config,
        response_schema=PromptedSchema(CrossCheckReport),
    )

    reply = await checker.ask(
        "Findings:\n"
        "- [theorist d=0] Spin fluctuations dominate pairing\n"
        "- [analyst d=1] Phonon contribution non-negligible at overdoping\n"
    )

    report = await reply.content(retries=2)
    if report:
        print(f"\nContradictions: {len(report.contradictions)}")
        print(f"Gaps: {len(report.gaps)}")
        print(f"Summary: {report.summary[:200]}")
    else:
        print(f"\nRaw reply: {reply.body[:300]}")


asyncio.run(main())
