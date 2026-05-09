from __future__ import annotations

from typing import Any

import lionagi as li

from .models import ResearchPlan, TeamSpec

PLANNER_SYSTEM = """\
You are a research orchestrator. Given a topic, design a DAG of specialist teams.

Rules:
- Each team has ONE clear deliverable
- Teams with no depends_on run in parallel (wave 1)
- 2-4 agents per team: first receives prompt, last says TERMINATE
- Agent names must be unique ACROSS ALL TEAMS
- Prefer wide (3 parallel teams) over deep (3 sequential teams)
- Always include a final synthesis team that depends_on all others
- synthesis_instruction tells the merge how to combine outputs
"""


async def create_plan(
    topic: str,
    *,
    planner_model: li.iModel | None = None,
    guidance: str = "",
) -> ResearchPlan:
    if planner_model is None:
        planner_model = li.iModel(provider="openrouter", model="google/gemini-3-flash-preview")

    branch = li.Branch(
        chat_model=planner_model,
        system=PLANNER_SYSTEM,
    )

    instruction = f"Design a research plan for: {topic}"
    if guidance:
        instruction += f"\n\nAdditional guidance: {guidance}"

    result = await branch.operate(
        instruction=instruction,
        response_format=ResearchPlan,
    )
    return result
