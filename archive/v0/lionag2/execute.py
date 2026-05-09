from __future__ import annotations

import asyncio
import logging
from typing import Any

import lionagi as li
from lionagi.service.types import StreamChunk

from .models import ResearchPlan, TeamResult, TeamSpec

logger = logging.getLogger(__name__)


def _build_agent_configs(team: TeamSpec) -> list[dict[str, Any]]:
    configs = []
    for i, (name, role) in enumerate(zip(team.agent_names, team.agent_roles)):
        is_last = i == len(team.agent_names) - 1
        handoffs = []
        if not is_last:
            handoffs.append({
                "target": team.agent_names[i + 1],
                "condition": f"When {name} has completed their part",
            })

        system_msg = f"You are {name}, a {role}. "
        if is_last:
            system_msg += "When you are satisfied with the output, say TERMINATE."
        else:
            system_msg += f"Hand off to {team.agent_names[i + 1]} when your part is done."

        configs.append({
            "name": name,
            "role": role,
            "system_message": system_msg,
            "tools": [],
            "handoffs": handoffs,
        })
    return configs


async def execute_team(
    team: TeamSpec,
    context: str = "",
    *,
    llm_config: dict[str, Any] | None = None,
) -> TeamResult:
    if llm_config is None:
        import os
        llm_config = {
            "config_list": [{
                "model": "google/gemini-3-flash-preview",
                "api_key": os.environ.get("OPENROUTER_API_KEY", os.environ.get("GEMINI_API_KEY", "")),
                "base_url": "https://openrouter.ai/api/v1",
                "default_headers": {"HTTP-Referer": "https://khive.ai", "X-Title": "lionag2"},
            }],
        }

    agent_configs = _build_agent_configs(team)

    model = li.iModel(
        provider="ag2",
        agent_configs=agent_configs,
        llm_config=llm_config,
    )

    prompt = f"Team objective: {team.objective}"
    if context:
        prompt += f"\n\nContext from prior teams:\n{context}"

    branch = li.Branch(chat_model=model)
    result = await branch.operate(instruction=prompt)

    return TeamResult(
        team_id=team.id,
        output=str(result),
        agent_count=len(agent_configs),
        rounds_used=team.max_round,
    )


async def execute_plan(
    plan: ResearchPlan,
    *,
    llm_config: dict[str, Any] | None = None,
    on_team_start: Any = None,
    on_team_done: Any = None,
    hooks: Any = None,
) -> dict[str, TeamResult]:
    results: dict[str, TeamResult] = {}
    completed: set[str] = set()
    teams_by_id = {t.id: t for t in plan.teams}

    def ready(team: TeamSpec) -> bool:
        return all(d in completed for d in team.depends_on)

    while len(completed) < len(plan.teams):
        wave = [t for t in plan.teams if t.id not in completed and ready(t)]
        if not wave:
            remaining = [t.id for t in plan.teams if t.id not in completed]
            raise RuntimeError(f"Deadlock: no team ready. Remaining: {remaining}")

        for t in wave:
            if hooks:
                await hooks.on_team_start(t)
            if on_team_start:
                on_team_start(t)

        async def _run(team: TeamSpec) -> TeamResult:
            context_parts = []
            for dep_id in team.depends_on:
                if dep_id in results:
                    context_parts.append(
                        f"[{dep_id}]: {results[dep_id].output[:2000]}"
                    )
            context = "\n\n".join(context_parts)
            if hooks:
                context = hooks.truncate_context(context)
            return await execute_team(team, context, llm_config=llm_config)

        wave_results = await asyncio.gather(*[_run(t) for t in wave])

        for team, result in zip(wave, wave_results):
            results[team.id] = result
            completed.add(team.id)
            if hooks:
                await hooks.on_team_done(team, result)
            if on_team_done:
                on_team_done(team, result)

    return results
