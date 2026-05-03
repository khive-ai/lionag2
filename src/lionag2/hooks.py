"""Execution hooks using AG2 beta abstractions.

No reimplementation — direct use of autogen.beta observer, policies,
knowledge, and stream primitives.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from autogen.beta.events.alert import ObserverAlert, Severity
from autogen.beta.knowledge.memory import MemoryKnowledgeStore
from autogen.beta.observer.loop_detector import LoopDetector
from autogen.beta.observer.token_monitor import TokenMonitor
from autogen.beta.policies.sliding_window import SlidingWindowPolicy
from autogen.beta.policies.token_budget import TokenBudgetPolicy
from autogen.beta.stream import MemoryStream

logger = logging.getLogger(__name__)


@dataclass
class ResearchHooks:
    """Bundled AG2 beta hooks for the lionag2 execution pipeline.

    Uses AG2's own LoopDetector, TokenMonitor, SlidingWindowPolicy,
    TokenBudgetPolicy, and MemoryKnowledgeStore — not reimplementations.
    """

    loop_detector: LoopDetector = field(default_factory=LoopDetector)
    token_monitor: TokenMonitor = field(default_factory=TokenMonitor)
    window_policy: SlidingWindowPolicy = field(
        default_factory=lambda: SlidingWindowPolicy(max_events=20)
    )
    budget_policy: TokenBudgetPolicy = field(
        default_factory=lambda: TokenBudgetPolicy(max_tokens=8000)
    )
    knowledge: MemoryKnowledgeStore = field(default_factory=MemoryKnowledgeStore)
    stream: MemoryStream = field(default_factory=MemoryStream)
    _team_outputs: dict[str, str] = field(default_factory=dict)

    async def on_team_start(self, team):
        self.loop_detector.reset()
        await self.knowledge.write(
            f"/teams/{team.id}/status", "running"
        )
        logger.info("[hooks] Team %s started (%d agents)", team.id, len(team.agent_names))

    async def on_team_done(self, team, result):
        self._team_outputs[team.id] = result.output[:2000]
        await self.knowledge.write(
            f"/teams/{team.id}/status", "completed"
        )
        await self.knowledge.write(
            f"/teams/{team.id}/output", result.output[:4000]
        )
        alert = self.token_monitor.record(0)
        if alert:
            logger.warning("[hooks] %s", alert)
        logger.info("[hooks] Team %s completed (%d chars)", team.id, len(result.output))

    def truncate_context(self, context: str) -> str:
        max_chars = self.budget_policy.max_tokens * self.budget_policy.chars_per_token
        if len(context) <= max_chars:
            return context
        return context[-max_chars:]

    async def recall_team(self, team_id: str) -> str | None:
        return await self.knowledge.read(f"/teams/{team_id}/output")

    async def list_teams(self) -> list[str]:
        paths = await self.knowledge.list("/teams/")
        return [p.split("/")[2] for p in paths if p.endswith("/status")]

    async def report(self) -> dict[str, Any]:
        teams = await self.list_teams()
        return {
            "teams_completed": len(self._team_outputs),
            "team_ids": list(self._team_outputs.keys()),
            "tokens_tracked": self.token_monitor.total_tokens,
            "knowledge_paths": await self.knowledge.list("/"),
        }
