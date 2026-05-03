from __future__ import annotations

import logging
from typing import Any

import lionagi as li

from .execute import execute_plan
from .hooks import ResearchHooks
from .models import ResearchPlan, TeamResult
from .plan import create_plan

logger = logging.getLogger(__name__)


async def research(
    topic: str,
    *,
    planner_model: li.iModel | None = None,
    executor_llm_config: dict[str, Any] | None = None,
    guidance: str = "",
    synthesize: bool = True,
    hooks: ResearchHooks | None = None,
) -> str:
    # Phase 1: Plan
    print(f"\n{'='*60}")
    print(f"[lionag2] Planning research: {topic}")
    print(f"{'='*60}")

    plan = await create_plan(topic, planner_model=planner_model, guidance=guidance)

    print(f"\nPlan: {len(plan.teams)} teams")
    for t in plan.teams:
        deps = f" (after: {', '.join(t.depends_on)})" if t.depends_on else " (wave 1)"
        print(f"  [{t.id}] {t.name}: {len(t.agent_names)} agents{deps}")

    # Phase 2: Execute DAG
    print(f"\n{'='*60}")
    print("[lionag2] Executing teams...")
    print(f"{'='*60}")

    def on_start(team):
        print(f"\n  >> Starting [{team.id}] {team.name}")

    def on_done(team, result):
        preview = result.output[:200].replace('\n', ' ')
        print(f"  << Done [{team.id}]: {preview}...")

    if hooks is None:
        hooks = ResearchHooks()

    results = await execute_plan(
        plan,
        llm_config=executor_llm_config,
        on_team_start=on_start,
        on_team_done=on_done,
        hooks=hooks,
    )

    # Phase 3: Synthesize
    if not synthesize:
        return "\n\n".join(
            f"## {r.team_id}\n{r.output}" for r in results.values()
        )

    print(f"\n{'='*60}")
    print("[lionag2] Synthesizing results...")
    print(f"{'='*60}")

    synth_model = planner_model or li.iModel(provider="openrouter", model="google/gemini-3-flash-preview")
    synth_branch = li.Branch(
        chat_model=synth_model,
        system="You synthesize research team outputs into a coherent final report.",
    )

    team_outputs = "\n\n".join(
        f"## Team: {r.team_id}\n{r.output}" for r in results.values()
    )

    final = await synth_branch.communicate(
        instruction=(
            f"Synthesize these team outputs into a final research report.\n\n"
            f"Synthesis instruction: {plan.synthesis_instruction}\n\n"
            f"Team outputs:\n{team_outputs}"
        ),
    )

    print(f"\n{'='*60}")
    print("[lionag2] Research complete.")
    print(f"{'='*60}")

    if hooks:
        report = await hooks.report()
        logger.info("[lionag2] Execution report: %s", report)

    return str(final)
