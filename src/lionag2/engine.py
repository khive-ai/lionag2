"""Reactive recursive research engine on AG2 beta.

Architecture:
  Event bus (MemoryStream) + watches = reactive coordination.
  Per-team streams = agent context. StreamManager carries context
  between depths. The research tree EMERGES from event flow:

  survey → FindingEmitted → (watch) → DepthRequest → spawn child
  findings batch (CadenceWatch) → analysis team
  AnalysisComplete → review team
  paper gaps → DepthRequest → reactive system fills them

  AG2 primitives: Agent, MemoryStream, EventWatch, CadenceWatch,
  observer, as_tool, persistent_stream, ExaToolkit, SandboxCodeTool,
  WebFetchTool, AGUIStream.
"""

import asyncio
import logging
import os
import time
import uuid
from collections.abc import Callable
from typing import Any

from autogen.beta import Agent, KnowledgeConfig, PromptedSchema
from autogen.beta.compact import CompactTrigger, TailWindowCompact
from autogen.beta.config import OpenAIConfig
from autogen.beta.events import BaseEvent, ToolResultsEvent
from autogen.beta.knowledge import MemoryKnowledgeStore
from autogen.beta.policies import ConversationPolicy, SlidingWindowPolicy
from autogen.beta.tools import ExaToolkit, SandboxCodeTool
from autogen.beta.watch import CadenceWatch, EventWatch

from .events import (
    ContradictionFound,
    DepthRequested,
    FindingEmitted,
    PaperGapEvent,
    PivotDetected,
)
from .khive_toolkit import KhiveToolkit, khive_available
from .models import (
    CrossCheckReport,
    PaperDraft,
)
from .prompts import ALL_SPECIALISTS, CONNECTOR, CROSS_CHECK, PAPER_WRITER
from .streams import StreamManager
from .tools import EMISSION_TOOLS

logger = logging.getLogger("lionag2.engine")
SSECallback = Callable[[dict[str, Any]], Any]


class ResearchEngine:
    """Event-driven recursive research engine.

    Two-stream architecture:
      - Event bus: typed coordination events, watches subscribe here
      - Per-team streams: each team.ask() gets its own, no lock contention
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5.4-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        max_depth: int = 3,
        novelty_threshold: float = 0.7,
        findings_batch_size: int = 3,
        findings_batch_timeout: float = 120.0,
        paper_max_iterations: int = 2,
        paper_quality_threshold: float = 0.7,
        extra_specialists: list[dict[str, Any]] | None = None,
        khive_api_key: str | None = None,
        khive_namespace: str = "lionag2",
        daytona_image: str = "python:3.12",
        on_event: SSECallback | None = None,
    ) -> None:
        config_kw: dict[str, Any] = {}
        key = api_key or os.getenv("OPENAI_API_KEY")
        if key:
            config_kw["api_key"] = key
        if base_url:
            config_kw["base_url"] = base_url
        self.config = OpenAIConfig(model, **config_kw)

        self.max_depth = max_depth
        self.novelty_threshold = novelty_threshold
        self.batch_size = findings_batch_size
        self.batch_timeout = findings_batch_timeout
        self.paper_max_iterations = paper_max_iterations
        self.paper_quality_threshold = paper_quality_threshold
        self.on_event = on_event
        self._extra_specialists = extra_specialists or []

        # AG2 native tools — Exa handles both search AND content fetching
        self._exa: ExaToolkit | None = None
        if os.getenv("EXA_API_KEY"):
            self._exa = ExaToolkit()
        self._sandbox: SandboxCodeTool | None = None
        if os.getenv("DAYTONA_API_KEY"):
            try:
                from autogen.beta.extensions.daytona import DaytonaCodeEnvironment

                self._sandbox = SandboxCodeTool(DaytonaCodeEnvironment(image=daytona_image))
            except ImportError:
                logger.warning("daytona SDK not installed")

        # Khive toolkit — tools for agents that need explicit memory/graph/messaging
        self._khive: KhiveToolkit | None = None
        if khive_available() and (khive_api_key or os.getenv("KHIVE_API_KEY")):
            self._khive = KhiveToolkit(api_key=khive_api_key, namespace=khive_namespace)

        # Knowledge store — khive backend when available, AG2 MemoryKnowledgeStore fallback.
        # AG2's harness (WorkingMemoryPolicy, EpisodicMemoryPolicy, compaction,
        # aggregation) all run through this store automatically.
        if khive_available() and (khive_api_key or os.getenv("KHIVE_API_KEY")):
            from .khive_store import KhiveKnowledgeStore

            self._knowledge_store = KhiveKnowledgeStore(
                api_key=khive_api_key, namespace=khive_namespace,
            )
        else:
            self._knowledge_store = MemoryKnowledgeStore()

        self._knowledge_config = KnowledgeConfig(
            store=self._knowledge_store,
            compact=TailWindowCompact(target=30),
            compact_trigger=CompactTrigger(max_events=50),
        )

        # Stream architecture
        self.streams = StreamManager()
        self.title_to_url: dict[str, str] = {}
        self._active_tasks: set[asyncio.Task] = set()
        self._watches: list[Any] = []
        self._node_depths: dict[str, int] = {}
        self._seen_topics: set[str] = set()

    # -- Agent construction ---------------------------------------------------

    def _resolve_tools(self, tool_tags: tuple[str, ...]) -> list:
        available: dict[str, Any] = {}
        if self._exa:
            available["search"] = self._exa
            available["fetch"] = self._exa
        if self._sandbox:
            available["run_code"] = self._sandbox

        tools = []
        seen = set()
        for tag in tool_tags:
            if tag in available and id(available[tag]) not in seen:
                tools.append(available[tag])
                seen.add(id(available[tag]))
        tools.extend(EMISSION_TOOLS)
        if self._khive:
            tools.append(self._khive)
        return tools

    def _make_agent(self, spec: dict[str, Any]) -> Agent:
        tools = self._resolve_tools(spec["tools"])

        agent_model = spec.get("model")
        if agent_model:
            config_kw: dict[str, Any] = {}
            if self.config._api_key:
                config_kw["api_key"] = self.config._api_key
            agent_config = OpenAIConfig(agent_model, **config_kw)
        else:
            agent_config = self.config

        agent = Agent(
            spec["name"],
            prompt=spec["prompt"],
            config=agent_config,
            tools=tools,
            variables={"agent_name": spec["name"], "role": spec["role"]},
            knowledge=self._knowledge_config,
            assembly=[
                ConversationPolicy(),
                SlidingWindowPolicy(max_events=40, transparent=True),
            ],
        )

        @agent.observer(ToolResultsEvent)
        def _capture_urls(event: ToolResultsEvent) -> None:
            for r in event.results:
                data = r.result.parts[0].data
                for hit in getattr(data, "results", None) or []:
                    title = getattr(hit, "title", None)
                    url = getattr(hit, "url", None)
                    if title and url:
                        self.title_to_url[title] = url

        return agent

    # -- Team runner ----------------------------------------------------------

    async def _run_team(
        self,
        instruction: str,
        *,
        parent_stream: str | None = None,
        depth: int = 0,
        node_id: str = "",
    ) -> str:
        """Run the full specialist team sequentially on a shared stream."""
        team_name = f"team_d{depth}_{uuid.uuid4().hex[:6]}"
        team_stream = self.streams.get_or_create(team_name)

        if parent_stream:
            carried = await self.streams.carry_for_depth(parent_stream, team_stream, depth)
            logger.debug("Carry-over: %d events %s → %s", carried, parent_stream, team_name)

        # Core specialists + user-added extras + Connector (khive only)
        roster = list(ALL_SPECIALISTS)
        roster.extend(self._extra_specialists)
        if self._khive:
            roster.append(CONNECTOR)

        self._emit(
            {
                "type": "team_active",
                "node_id": node_id,
                "agents": [s["name"] for s in roster],
                "depth": depth,
            }
        )

        last_reply = ""
        for i, spec in enumerate(roster):
            agent = self._make_agent(spec)
            turn = (
                instruction
                if i == 0
                else (f"Building on the previous agent's work, continue:\n\n{last_reply[:2000]}")
            )
            self._emit({"type": "agent_turn", "node_id": node_id, "agent": spec["name"]})

            try:
                reply = await agent.ask(turn, stream=team_stream)
                last_reply = reply.body or ""
                self._emit(
                    {
                        "type": "agent_done",
                        "node_id": node_id,
                        "agent": spec["name"],
                        "chars": len(last_reply),
                    }
                )
            except Exception as exc:
                logger.error("Agent %s failed: %s", spec["name"], exc)
                self._emit(
                    {
                        "type": "agent_error",
                        "node_id": node_id,
                        "agent": spec["name"],
                        "error": str(exc),
                    }
                )
                last_reply = f"[{spec['name']} failed: {exc}]"

        return last_reply

    # -- Reactive handlers (watches on event bus) -----------------------------

    async def _on_finding(self, events: list[BaseEvent], ctx: Any) -> None:
        for event in events:
            if not isinstance(event, FindingEmitted):
                continue
            self._emit(
                {
                    "type": "finding",
                    "claim": event.claim,
                    "novelty": event.novelty,
                    "source": event.source_agent,
                    "depth": event.depth,
                }
            )

            if event.novelty > self.novelty_threshold and event.depth < self.max_depth:
                await self.streams.emit_to_bus(
                    DepthRequested(
                        question=f"Drill deeper: {event.claim}",
                        novelty=event.novelty,
                        parent_depth=event.depth,
                    )
                )

    async def _on_depth_request(self, events: list[BaseEvent], ctx: Any) -> None:
        for event in events:
            if not isinstance(event, DepthRequested):
                continue
            new_depth = event.parent_depth + 1
            if new_depth > self.max_depth:
                continue
            normalized = event.question.lower()[:40]
            if normalized in self._seen_topics:
                self._emit(
                    {"type": "node_pruned", "question": event.question, "reason": "duplicate"}
                )
                continue
            self._seen_topics.add(normalized)

            child_id = uuid.uuid4().hex[:12]
            self._node_depths[child_id] = new_depth
            self._emit(
                {
                    "type": "child_spawned",
                    "child_id": child_id,
                    "question": event.question,
                    "depth": new_depth,
                    "novelty": event.novelty,
                }
            )

            parent_stream = None
            for name in self.streams.all_streams:
                if f"_d{event.parent_depth}_" in name:
                    parent_stream = name
                    break

            self._spawn(self._run_depth_node(event.question, new_depth, parent_stream, child_id))

    async def _on_findings_batch(self, events: list[BaseEvent], ctx: Any) -> None:
        findings = [e for e in events if isinstance(e, FindingEmitted)]
        if findings:
            logger.info("Findings batch: %d findings accumulated", len(findings))

    async def _on_contradiction(self, events: list[BaseEvent], ctx: Any) -> None:
        for event in events:
            if isinstance(event, ContradictionFound):
                self._emit(
                    {
                        "type": "contradiction",
                        "claim_a": event.claim_a,
                        "claim_b": event.claim_b,
                        "severity": event.severity,
                    }
                )

    async def _on_pivot(self, events: list[BaseEvent], ctx: Any) -> None:
        for event in events:
            if isinstance(event, PivotDetected):
                self._emit(
                    {
                        "type": "pivot",
                        "description": event.description,
                        "source": event.source_agent,
                    }
                )

    async def _on_paper_gap(self, events: list[BaseEvent], ctx: Any) -> None:
        for event in events:
            if not isinstance(event, PaperGapEvent) or event.priority != "high":
                continue
            await self.streams.emit_to_bus(
                DepthRequested(
                    question=event.research_question,
                    novelty=0.8,
                    parent_depth=max(self._node_depths.values(), default=0),
                )
            )

    # -- Pipeline stages ------------------------------------------------------

    async def _run_depth_node(
        self, topic: str, depth: int, parent_stream: str | None, node_id: str
    ) -> None:
        self._emit({"type": "node_active", "node_id": node_id, "topic": topic, "depth": depth})

        from .prompts import build_node_instruction

        instruction = build_node_instruction(topic, depth, self.max_depth)

        result = await self._run_team(
            instruction, parent_stream=parent_stream, depth=depth, node_id=node_id
        )

        await self.streams.emit_to_bus(
            FindingEmitted(
                claim=topic,
                evidence=result[:500],
                novelty=0.8,
                source_agent="team",
                depth=depth,
            )
        )
        self._emit({"type": "node_complete", "node_id": node_id, "depth": depth})

    async def _run_cross_check(self) -> CrossCheckReport:
        self._emit({"type": "cross_check_start"})
        all_findings = await self.streams.collect_all_findings()
        if not all_findings:
            return CrossCheckReport(summary="No findings to cross-check.")

        ctx = "\n".join(f"- [{f.source_agent} d={f.depth}] {f.claim}" for f in all_findings)
        checker = Agent(
            "cross_checker",
            prompt=CROSS_CHECK,
            config=self.config,
            response_schema=PromptedSchema(CrossCheckReport),
        )
        stream = self.streams.get_or_create("cross_check")
        reply = await checker.ask(
            f"Cross-check {len(all_findings)} findings:\n{ctx}", stream=stream
        )
        report = await reply.content(retries=1)
        if report is None:
            report = CrossCheckReport(summary=reply.body or "")
        self._emit(
            {
                "type": "cross_check_done",
                "contradictions": len(report.contradictions),
                "gaps": len(report.gaps),
            }
        )
        return report

    async def _run_paper_loop(self, cross_report: CrossCheckReport) -> PaperDraft:
        """Write paper → evaluate → gaps emit DepthRequests → reactive fill → rewrite."""
        paper: PaperDraft | None = None
        all_findings = await self.streams.collect_all_findings()

        for iteration in range(self.paper_max_iterations):
            self._emit({"type": "paper_iteration", "iteration": iteration})

            findings_text = "\n".join(
                f"- [{f.source_agent} d={f.depth} conf={f.confidence:.1f}]"
                f" {f.claim}: {f.evidence[:200]}"
                for f in all_findings
            )
            payload = (
                f"# Research findings ({len(all_findings)} total)\n{findings_text}\n\n"
                f"# Cross-check\n{cross_report.model_dump_json(indent=2)}\n"
            )
            if paper:
                payload += (
                    f"\n# Previous draft (quality={paper.quality_score:.2f})\nFill these gaps:\n"
                )
                for g in paper.gaps:
                    payload += f"  - [{g.priority}] {g.section}: {g.description}\n"

            writer = Agent(
                "paper_writer",
                prompt=PAPER_WRITER,
                config=self.config,
                response_schema=PromptedSchema(PaperDraft),
            )
            stream = self.streams.get_or_create(f"paper_{iteration}")
            reply = await writer.ask(payload, stream=stream)
            paper = await reply.content(retries=1)
            if paper is None:
                paper = PaperDraft(
                    title="Research",
                    abstract="Generation failed.",
                    body_markdown=reply.body or "",
                    quality_score=0.0,
                )

            self._emit(
                {
                    "type": "paper_draft",
                    "iteration": iteration,
                    "quality": paper.quality_score,
                    "gaps": len(paper.gaps),
                }
            )

            if paper.quality_score >= self.paper_quality_threshold:
                break

            # High-priority gaps → DepthRequests → reactive system handles them
            high_gaps = [g for g in paper.gaps if g.priority == "high"]
            if not high_gaps or iteration == self.paper_max_iterations - 1:
                break

            for gap in high_gaps:
                await self.streams.emit_to_bus(
                    PaperGapEvent(
                        section=gap.section,
                        description=gap.description,
                        research_question=gap.research_question,
                        priority=gap.priority,
                    )
                )

            # Wait for reactive depth nodes to settle
            while self._active_tasks:
                await asyncio.gather(*self._active_tasks, return_exceptions=True)

            # Refresh findings after gap-filling
            all_findings = await self.streams.collect_all_findings()

        return paper

    # -- Main entry point -----------------------------------------------------

    async def run(self, topic: str) -> PaperDraft:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic is empty")

        root_id = uuid.uuid4().hex[:12]
        self._node_depths[root_id] = 0
        self._seen_topics.add(topic.lower()[:40])

        self._emit(
            {"type": "tree_init", "root_id": root_id, "topic": topic, "max_depth": self.max_depth}
        )

        # Arm reactive watches on event bus
        bus = self.streams.bus
        watchers = [
            (EventWatch(FindingEmitted), self._on_finding),
            (EventWatch(DepthRequested), self._on_depth_request),
            (EventWatch(ContradictionFound), self._on_contradiction),
            (EventWatch(PivotDetected), self._on_pivot),
            (EventWatch(PaperGapEvent), self._on_paper_gap),
            (
                CadenceWatch(
                    n=self.batch_size, max_wait=self.batch_timeout, condition=FindingEmitted
                ),
                self._on_findings_batch,
            ),
        ]
        for watch, handler in watchers:
            watch.arm(bus, handler)
            self._watches.append(watch)

        # Kick off root exploration
        from .prompts import build_node_instruction

        instruction = build_node_instruction(topic, 0, self.max_depth)
        await self._run_team(instruction, depth=0, node_id=root_id)

        # Wait for reactive graph to quiesce
        while self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

        self._emit({"type": "exploration_settled", "nodes": len(self._node_depths)})

        # Cross-check
        cross_report = await self._run_cross_check()

        # Iterative paper with gap → DepthRequest feedback
        paper = await self._run_paper_loop(cross_report)

        # Disarm watches
        for w in self._watches:
            if w.is_armed:
                w.disarm()
        self._watches.clear()

        total_findings = len(await self.streams.collect_all_findings())
        self._emit(
            {
                "type": "exploration_done",
                "total_nodes": len(self._node_depths),
                "total_findings": total_findings,
                "max_depth": max(self._node_depths.values(), default=0),
                "paper_quality": paper.quality_score,
            }
        )
        return paper

    # -- Serving (ag-ui protocol) ---------------------------------------------

    def as_agui_stream(self):
        """Return AGUIStream for ASGI serving with ag-ui protocol."""
        from autogen.beta.ag_ui import AGUIStream

        agent = Agent("lionag2", prompt="Recursive research agent.", config=self.config)
        return AGUIStream(agent)

    # -- Utilities ------------------------------------------------------------

    def _emit(self, event: dict[str, Any]) -> None:
        event.setdefault("timestamp", time.time())
        if self.on_event:
            self.on_event(event)

    def _spawn(self, coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)
        return task


async def research(
    topic: str,
    *,
    model: str = "gpt-5.4-mini",
    max_depth: int = 3,
    on_event: SSECallback | None = None,
    **kwargs: Any,
) -> PaperDraft:
    engine = ResearchEngine(model=model, max_depth=max_depth, on_event=on_event, **kwargs)
    return await engine.run(topic)
