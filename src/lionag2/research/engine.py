"""Reactive recursive research engine — Flow-native."""

import asyncio
import logging
import os
import uuid
from collections.abc import Callable
from typing import Any

from autogen.beta import Agent, KnowledgeConfig, PromptedSchema
from autogen.beta.compact import CompactTrigger, TailWindowCompact
from autogen.beta.config import OpenAIConfig
from autogen.beta.events import BaseEvent, ToolResultsEvent
from autogen.beta.knowledge import MemoryKnowledgeStore
from autogen.beta.policies import ConversationPolicy
from autogen.beta.tools import ExaToolkit, SandboxCodeTool

from ..core import Flow, SafeSlidingWindowPolicy
from ..tools import KhiveToolkit, khive_available
from .events import (
    ContradictionFound,
    CrossCheckDone,
    DepthRequested,
    ExplorationComplete,
    FindingEmitted,
    HandoffRequested,
    NodeRegistered,
    PaperDrafted,
    PaperGapEvent,
    PivotDetected,
    TeamStarted,
    TopicSeen,
    UrlCaptured,
)
from .middleware import clean_search_results
from .models import CrossCheckReport, PaperDraft
from .prompts import ALL_SPECIALISTS, CONNECTOR, CROSS_CHECK, PAPER_WRITER, build_node_instruction
from .tools import EMISSION_TOOLS, PAPER_TOOLS

logger = logging.getLogger("lionag2.engine")
SSECallback = Callable[[dict[str, Any]], Any]


class ResearchEngine:
    """Flow-native recursive research engine.

    Architecture:
        - Each agent gets per-agent stream for isolated AG2 turns
        - Bridge observers on each agent forward research events
          (FindingEmitted, DepthRequested, etc.) to the engine
        - Engine coordinates depth expansion and paper writing
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5.4-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        max_depth: int = 3,
        max_concurrent: int = 5,
        novelty_threshold: float = 0.7,
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
        self.max_concurrent = max_concurrent
        self.novelty_threshold = novelty_threshold
        self.paper_max_iterations = paper_max_iterations
        self.paper_quality_threshold = paper_quality_threshold
        self.on_event = on_event
        self._extra_specialists = extra_specialists or []

        self._sandbox: SandboxCodeTool | None = None
        if os.getenv("DAYTONA_API_KEY"):
            try:
                from autogen.beta.extensions.daytona import DaytonaCodeEnvironment

                self._sandbox = SandboxCodeTool(DaytonaCodeEnvironment(image=daytona_image))
            except ImportError:
                logger.warning("daytona SDK not installed")

        self._has_khive = khive_available() and bool(khive_api_key or os.getenv("KHIVE_API_KEY"))
        self._khive_api_key = khive_api_key
        self._khive_namespace = khive_namespace

        if self._has_khive:
            from ..tools import KhiveKnowledgeStore

            self._knowledge_store = KhiveKnowledgeStore(
                api_key=khive_api_key, namespace=khive_namespace
            )
        else:
            self._knowledge_store = MemoryKnowledgeStore()

        self._knowledge_config = KnowledgeConfig(
            store=self._knowledge_store,
            compact=TailWindowCompact(target=30),
            compact_trigger=CompactTrigger(max_events=50),
        )

        self.flow = Flow(name="research")
        self._active_tasks: set[asyncio.Task] = set()
        self._pending_coros: list[Any] = []

    # -- Helpers --------------------------------------------------------------

    def _record(self, event: BaseEvent) -> None:
        self.flow.include(event)
        if self.on_event:
            d = event.to_dict()
            d["type"] = type(event).__name__
            self.on_event(d)

    def _notify(self, kind: str, **data: Any) -> None:
        if self.on_event:
            self.on_event({"type": kind, **data})

    def _topic_seen(self, normalized: str) -> bool:
        return any(ts.normalized == normalized for ts in self.flow.items[TopicSeen])

    def _current_max_depth(self) -> int:
        nodes = self.flow.items[NodeRegistered]
        return max((n.depth for n in nodes), default=0)

    # -- Agent construction ---------------------------------------------------

    def _resolve_tools(self, tool_tags: tuple[str, ...]) -> list:
        tools = []
        tags = set(tool_tags)

        if ("search" in tags or "fetch" in tags) and os.getenv("EXA_API_KEY"):
            exa = ExaToolkit(num_results=5, max_characters=5000, middleware=(clean_search_results,))
            tools.extend(exa.tools)

        if "run_code" in tags and self._sandbox:
            tools.append(self._sandbox)

        tools.extend(EMISSION_TOOLS)

        if self._has_khive and tags & {"memory", "graph", "messages"}:
            tools.extend(
                KhiveToolkit(api_key=self._khive_api_key, namespace=self._khive_namespace).tools
            )
        return tools

    def _make_agent(self, spec: dict[str, Any], *, depth: int = 0, node_id: str = "") -> Agent:
        tools = self._resolve_tools(spec["tools"])

        if spec.get("model"):
            config_kw: dict[str, Any] = {}
            if self.config.api_key:
                config_kw["api_key"] = self.config.api_key
            agent_config = OpenAIConfig(spec["model"], **config_kw)
        else:
            agent_config = self.config

        agent = Agent(
            spec["name"],
            prompt=spec["prompt"],
            config=agent_config,
            tools=tools,
            variables={
                "agent_name": spec["name"],
                "role": spec["role"],
                "depth": depth,
                "node_id": node_id,
            },
            assembly=[
                ConversationPolicy(),
                SafeSlidingWindowPolicy(max_events=40, transparent=True),
            ],
        )

        engine = self

        @agent.observer(FindingEmitted)
        def _on_finding(event: FindingEmitted) -> None:
            engine._record(event)
            if event.novelty > engine.novelty_threshold and event.depth < engine.max_depth:
                engine._spawn(
                    engine._spawn_depth_node(
                        event.claim,
                        event.depth + 1,
                        node_id,
                    )
                )

        @agent.observer(DepthRequested)
        def _on_depth_req(event: DepthRequested) -> None:
            engine._record(event)
            engine._spawn(
                engine._spawn_depth_node(
                    event.question,
                    event.parent_depth + 1,
                    event.parent_node_id or node_id,
                )
            )

        @agent.observer(ContradictionFound)
        def _on_contradiction(event: ContradictionFound) -> None:
            engine._record(event)

        @agent.observer(PivotDetected)
        def _on_pivot(event: PivotDetected) -> None:
            engine._record(event)

        flow = self.flow

        @agent.observer(ToolResultsEvent)
        def _capture_urls(event: ToolResultsEvent) -> None:
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
                            flow.include(UrlCaptured(title=t, url=u))

        return agent

    # -- Depth expansion ------------------------------------------------------

    async def _spawn_depth_node(self, topic: str, depth: int, parent_node_id: str = "") -> None:
        if depth > self.max_depth:
            return
        normalized = topic.lower()[:40]
        if self._topic_seen(normalized):
            return

        self._record(TopicSeen(normalized=normalized))
        child_id = uuid.uuid4().hex[:12]
        team_name = f"team_d{depth}_{uuid.uuid4().hex[:6]}"
        self._record(
            NodeRegistered(
                node_id=child_id,
                topic=topic,
                depth=depth,
                parent_node_id=parent_node_id,
                stream_name=team_name,
            )
        )
        await self._run_team(
            build_node_instruction(topic, depth, self.max_depth),
            team_name=team_name,
            depth=depth,
            node_id=child_id,
            parent_node_id=parent_node_id,
        )

    # -- Team runner ----------------------------------------------------------

    async def _run_team(
        self,
        instruction: str,
        *,
        team_name: str,
        depth: int = 0,
        node_id: str = "",
        parent_node_id: str = "",
    ) -> str:
        if parent_node_id and depth > 0:
            parent_findings = [
                f for f in self.flow.items[FindingEmitted] if f.node_id == parent_node_id
            ]
            if parent_findings:
                prior = "\n".join(f"- [{f.source_agent}] {f.claim}" for f in parent_findings)
                instruction = f"{instruction}\n\n# Prior findings from depth {depth - 1}\n{prior}"

        roster = list(ALL_SPECIALISTS) + self._extra_specialists
        if self._has_khive:
            roster.append(CONNECTOR)

        self._record(TeamStarted(node_id=node_id, agents=[s["name"] for s in roster], depth=depth))
        roster_by_name = {s["name"]: s for s in roster}
        available = ", ".join(roster_by_name.keys())

        last_reply = ""
        current_idx = 0
        max_turns = len(roster) * 2

        for turn_num in range(max_turns):
            if current_idx >= len(roster):
                break
            spec = roster[current_idx]
            agent = self._make_agent(spec, depth=depth, node_id=node_id)

            turn = (
                f"{instruction}\n\nAvailable specialists for handoff: {available}, or 'done' to end."
                if turn_num == 0
                else f"Building on previous work, continue:\n\n{last_reply}\n\nAvailable for handoff: {available}, or 'done'."
            )
            self._notify("agent_start", node_id=node_id, agent=spec["name"])

            next_agent = [None]

            @agent.observer(HandoffRequested)
            def _on_handoff(event: HandoffRequested, _out=next_agent) -> None:
                _out[0] = event.next_agent

            try:
                reply = await agent.ask(
                    turn, stream=self.flow.streams[f"{team_name}_{spec['name']}_{turn_num}"]
                )
                last_reply = reply.body or ""
                self._notify(
                    "agent_done", node_id=node_id, agent=spec["name"], chars=len(last_reply)
                )
            except Exception as exc:
                logger.error("Agent %s failed: %s", spec["name"], exc)
                self._notify("agent_error", node_id=node_id, agent=spec["name"], error=str(exc))
                last_reply = f"[{spec['name']} failed: {exc}]"

            self._drain_pending()

            if next_agent[0] == "done":
                break
            if next_agent[0] and next_agent[0] in roster_by_name:
                current_idx = next(i for i, s in enumerate(roster) if s["name"] == next_agent[0])
            else:
                current_idx += 1

        return last_reply

    # -- Pipeline stages ------------------------------------------------------

    async def _run_cross_check(self) -> CrossCheckReport:
        all_findings = self.flow.items.by_type(FindingEmitted)
        if not all_findings:
            return CrossCheckReport(summary="No findings to cross-check.")

        checker = Agent(
            "cross_checker",
            prompt=CROSS_CHECK,
            config=self.config,
            response_schema=PromptedSchema(CrossCheckReport),
        )
        ctx_text = "\n".join(f"- [{f.source_agent} d={f.depth}] {f.claim}" for f in all_findings)
        reply = await checker.ask(
            f"Cross-check {len(all_findings)} findings:\n{ctx_text}",
            stream=self.flow.streams["cross_check"],
        )
        report = await reply.content(retries=1) or CrossCheckReport(summary=reply.body or "")
        self._record(
            CrossCheckDone(contradictions=len(report.contradictions), gaps=len(report.gaps))
        )
        return report

    def _build_writer_payload(
        self, cross_report: CrossCheckReport, prev_paper: PaperDraft | None,
    ) -> str:
        parts: list[str] = []

        findings = self.flow.items.by_type(FindingEmitted)
        parts.append(f"# Research Findings ({len(findings)} total)\n")
        for i, f in enumerate(findings, 1):
            parts.append(
                f"## Finding {i} [{f.source_agent}, depth={f.depth}]\n"
                f"- Claim: {f.claim}\n"
                f"- Evidence: {f.evidence}\n"
                f"- Novelty: {f.novelty:.2f} | Confidence: {f.confidence:.2f}\n"
            )

        urls = self.flow.items.by_type(UrlCaptured)
        if urls:
            parts.append(f"\n# Captured Sources ({len(urls)} URLs)\n")
            for u in urls:
                parts.append(f"- [{u.title}]({u.url})\n")

        contradictions = self.flow.items.by_type(ContradictionFound)
        if contradictions:
            parts.append(f"\n# Contradictions ({len(contradictions)})\n")
            for c in contradictions:
                parts.append(
                    f"- {c.source_a}: \"{c.claim_a}\" vs {c.source_b}: \"{c.claim_b}\" "
                    f"(severity={c.severity:.1f})\n"
                )

        pivots = self.flow.items.by_type(PivotDetected)
        if pivots:
            parts.append(f"\n# Pivots ({len(pivots)})\n")
            for p in pivots:
                parts.append(f"- [{p.source_agent}] {p.description}\n")

        parts.append(f"\n# Cross-Check Report\n{cross_report.model_dump_json(indent=2)}\n")

        if prev_paper:
            parts.append(
                f"\n# Previous Draft (quality={prev_paper.quality_score:.2f})\n"
                f"Fill the gaps identified. Previous gaps:\n"
            )
            for g in prev_paper.gaps:
                parts.append(f"- [{g.priority}] {g.section}: {g.description}\n")

        return "".join(parts)

    async def _run_paper_loop(self, cross_report: CrossCheckReport) -> PaperDraft:
        paper: PaperDraft | None = None
        engine = self

        for iteration in range(self.paper_max_iterations):
            payload = self._build_writer_payload(cross_report, paper)

            writer = Agent(
                "paper_writer",
                prompt=PAPER_WRITER,
                config=self.config,
                tools=PAPER_TOOLS,
                response_schema=PromptedSchema(PaperDraft),
            )

            @writer.observer(PaperGapEvent)
            def _on_gap(event: PaperGapEvent) -> None:
                engine._record(event)
                if event.priority == "high":
                    engine._spawn(
                        engine._spawn_depth_node(
                            event.research_question,
                            engine._current_max_depth() + 1,
                        )
                    )

            reply = await writer.ask(payload, stream=self.flow.streams[f"paper_{iteration}"])
            self._drain_pending()
            paper = await reply.content(retries=1) or PaperDraft(
                title="Research",
                abstract="Generation failed.",
                body_markdown=reply.body or "",
                quality_score=0.0,
            )
            self._record(
                PaperDrafted(iteration=iteration, quality=paper.quality_score, gaps=len(paper.gaps))
            )

            if paper.quality_score >= self.paper_quality_threshold:
                break

            while self._active_tasks:
                await asyncio.gather(*self._active_tasks, return_exceptions=True)

            if iteration == self.paper_max_iterations - 1:
                break

        return paper

    # -- Main -----------------------------------------------------------------

    async def run(self, topic: str) -> PaperDraft:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic is empty")

        self.flow.new_stream(FindingEmitted, name="findings")
        self.flow.new_stream(FindingEmitted.novelty > self.novelty_threshold, name="high_novelty")

        root_id = uuid.uuid4().hex[:12]
        root_team = f"team_d0_{uuid.uuid4().hex[:6]}"
        self._record(TopicSeen(normalized=topic.lower()[:40]))
        self._record(
            NodeRegistered(
                node_id=root_id,
                topic=topic,
                depth=0,
                stream_name=root_team,
            )
        )

        await self._run_team(
            build_node_instruction(topic, 0, self.max_depth),
            team_name=root_team,
            depth=0,
            node_id=root_id,
        )

        while self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

        cross_report = await self._run_cross_check()
        paper = await self._run_paper_loop(cross_report)

        while self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

        self._record(
            ExplorationComplete(
                total_nodes=len(self.flow.items.by_type(NodeRegistered)),
                total_findings=len(self.flow.items.by_type(FindingEmitted)),
                max_depth=self._current_max_depth(),
                paper_quality=paper.quality_score,
            )
        )
        return paper

    def _spawn(self, coro: Any) -> asyncio.Task | None:
        try:
            task = asyncio.create_task(coro)
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)
            return task
        except RuntimeError:
            self._pending_coros.append(coro)
            return None

    def _drain_pending(self) -> None:
        for coro in self._pending_coros:
            task = asyncio.create_task(coro)
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)
        self._pending_coros.clear()

    @property
    def urls(self) -> dict[str, str]:
        return {u.title: u.url for u in self.flow.items.by_type(UrlCaptured)}


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
