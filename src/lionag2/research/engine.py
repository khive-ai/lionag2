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
from autogen.beta.context import ConversationContext
from autogen.beta.events import BaseEvent, ToolResultsEvent
from autogen.beta.knowledge import MemoryKnowledgeStore
from autogen.beta.policies import ConversationPolicy
from autogen.beta.tools import ExaToolkit, SandboxCodeTool
from autogen.beta.watch import EventWatch

from ..core import Flow, SafeSlidingWindowPolicy
from ..tools import KhiveToolkit, khive_available

from .events import (
    AgentTurnDone,
    AgentTurnError,
    AgentTurnStarted,
    CrossCheckDone,
    DepthRequested,
    ExplorationComplete,
    FindingEmitted,
    NodeRegistered,
    PaperDrafted,
    PaperGapEvent,
    TeamStarted,
    TopicSeen,
    UrlCaptured,
)
from .middleware import clean_search_results
from .models import CrossCheckReport, PaperDraft
from .prompts import ALL_SPECIALISTS, CONNECTOR, CROSS_CHECK, PAPER_WRITER, build_node_instruction
from .tools import EMISSION_TOOLS

logger = logging.getLogger("lionag2.engine")
SSECallback = Callable[[dict[str, Any]], Any]


class ResearchEngine:
    """Flow-native recursive research engine.

    flow.items[FindingEmitted]   → all findings
    flow.items[NodeRegistered]   → all nodes
    flow.streams["bus"]          → coordination bus
    flow.streams["findings"]     → auto-routed findings view
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5.4-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        max_depth: int = 3,
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
            self._knowledge_store = KhiveKnowledgeStore(api_key=khive_api_key, namespace=khive_namespace)
        else:
            self._knowledge_store = MemoryKnowledgeStore()

        self._knowledge_config = KnowledgeConfig(
            store=self._knowledge_store,
            compact=TailWindowCompact(target=30),
            compact_trigger=CompactTrigger(max_events=50),
        )

        self.flow = Flow(name="research")
        self._active_tasks: set[asyncio.Task] = set()
        self._watches: list[Any] = []

    # -- Helpers --------------------------------------------------------------

    def _record(self, event: BaseEvent) -> None:
        self.flow.include(event)
        if self.on_event:
            d = event.to_dict()
            d["type"] = type(event).__name__
            self.on_event(d)

    async def _send_to_bus(self, event: BaseEvent) -> None:
        bus = self.flow.streams["bus"]
        await bus.send(event, ConversationContext(stream=bus))

    def _node_stream(self, node_id: str) -> str | None:
        for nr in self.flow.items[NodeRegistered]:
            if nr.node_id == node_id:
                return nr.stream_name
        return None

    def _current_max_depth(self) -> int:
        nodes = self.flow.items[NodeRegistered]
        return max((n.depth for n in nodes), default=0)

    def _topic_seen(self, normalized: str) -> bool:
        return any(ts.normalized == normalized for ts in self.flow.items[TopicSeen])

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
            tools.extend(KhiveToolkit(api_key=self._khive_api_key, namespace=self._khive_namespace).tools)
        return tools

    def _make_agent(self, spec: dict[str, Any]) -> Agent:
        tools = self._resolve_tools(spec["tools"])

        if spec.get("model"):
            config_kw: dict[str, Any] = {}
            if self.config._api_key:
                config_kw["api_key"] = self.config._api_key
            agent_config = OpenAIConfig(spec["model"], **config_kw)
        else:
            agent_config = self.config

        agent = Agent(
            spec["name"],
            prompt=spec["prompt"],
            config=agent_config,
            tools=tools,
            variables={"agent_name": spec["name"], "role": spec["role"]},
            knowledge=self._knowledge_config,
            assembly=[ConversationPolicy(), SafeSlidingWindowPolicy(max_events=40, transparent=True)],
        )

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

    # -- Team runner ----------------------------------------------------------

    async def _run_team(
        self, instruction: str, *, parent_node_id: str = "", depth: int = 0, node_id: str = "",
    ) -> str:
        team_name = f"team_d{depth}_{uuid.uuid4().hex[:6]}"

        if parent_node_id:
            ps = self._node_stream(parent_node_id)
            if ps:
                findings = [e for e in self.flow[ps] if isinstance(e, FindingEmitted)]
                if depth >= 2:
                    findings = [f for f in findings if f.novelty > 0.6][-5:]
                else:
                    findings = findings[-15:]
                for f in findings:
                    self.flow.include(f, progressions=[team_name])

        roster = list(ALL_SPECIALISTS) + self._extra_specialists
        if self._has_khive:
            roster.append(CONNECTOR)

        self._record(TeamStarted(node_id=node_id, agents=[s["name"] for s in roster], depth=depth))

        last_reply = ""
        for i, spec in enumerate(roster):
            agent = self._make_agent(spec)
            turn = instruction if i == 0 else f"Building on the previous agent's work, continue:\n\n{last_reply[:2000]}"
            self._record(AgentTurnStarted(node_id=node_id, agent=spec["name"]))

            try:
                reply = await agent.ask(turn, stream=self.flow.streams[f"{team_name}_{spec['name']}"])
                last_reply = reply.body or ""
                self._record(AgentTurnDone(node_id=node_id, agent=spec["name"], chars=len(last_reply)))
            except Exception as exc:
                logger.error("Agent %s failed: %s", spec["name"], exc)
                self._record(AgentTurnError(node_id=node_id, agent=spec["name"], error=str(exc)))
                last_reply = f"[{spec['name']} failed: {exc}]"

        return last_reply

    # -- Reactive handlers ----------------------------------------------------

    async def _on_finding(self, events: list[BaseEvent], ctx: Any) -> None:
        for e in events:
            if isinstance(e, FindingEmitted) and e.novelty > self.novelty_threshold and e.depth < self.max_depth:
                await self._send_to_bus(DepthRequested(
                    question=f"Drill deeper: {e.claim}", novelty=e.novelty, parent_depth=e.depth,
                ))

    async def _on_depth_request(self, events: list[BaseEvent], ctx: Any) -> None:
        for e in events:
            if not isinstance(e, DepthRequested):
                continue
            new_depth = e.parent_depth + 1
            if new_depth > self.max_depth:
                continue
            normalized = e.question.lower()[:40]
            if self._topic_seen(normalized):
                continue

            self._record(TopicSeen(normalized=normalized))
            child_id = uuid.uuid4().hex[:12]
            self._record(NodeRegistered(
                node_id=child_id, topic=e.question, depth=new_depth,
                parent_node_id=e.parent_node_id,
                stream_name=f"team_d{new_depth}_{uuid.uuid4().hex[:6]}",
            ))
            self._spawn(self._run_depth_node(e.question, new_depth, e.parent_node_id, child_id))

    async def _on_paper_gap(self, events: list[BaseEvent], ctx: Any) -> None:
        for e in events:
            if isinstance(e, PaperGapEvent) and e.priority == "high":
                await self._send_to_bus(DepthRequested(
                    question=e.research_question, novelty=0.8, parent_depth=self._current_max_depth(),
                ))

    # -- Pipeline stages ------------------------------------------------------

    async def _run_depth_node(self, topic: str, depth: int, parent_node_id: str, node_id: str) -> None:
        await self._run_team(
            build_node_instruction(topic, depth, self.max_depth),
            parent_node_id=parent_node_id, depth=depth, node_id=node_id,
        )
        await self._send_to_bus(FindingEmitted(
            claim=topic, evidence="(team summary)", novelty=0.8, source_agent="team", depth=depth,
        ))

    async def _run_cross_check(self) -> CrossCheckReport:
        all_findings = self.flow.items.by_type(FindingEmitted)
        if not all_findings:
            return CrossCheckReport(summary="No findings to cross-check.")

        checker = Agent(
            "cross_checker", prompt=CROSS_CHECK, config=self.config,
            response_schema=PromptedSchema(CrossCheckReport),
        )
        ctx_text = "\n".join(f"- [{f.source_agent} d={f.depth}] {f.claim}" for f in all_findings)
        reply = await checker.ask(
            f"Cross-check {len(all_findings)} findings:\n{ctx_text}",
            stream=self.flow.streams["cross_check"],
        )
        report = await reply.content(retries=1) or CrossCheckReport(summary=reply.body or "")
        self._record(CrossCheckDone(contradictions=len(report.contradictions), gaps=len(report.gaps)))
        return report

    async def _run_paper_loop(self, cross_report: CrossCheckReport) -> PaperDraft:
        paper: PaperDraft | None = None

        for iteration in range(self.paper_max_iterations):
            all_findings = self.flow.items.by_type(FindingEmitted)
            findings_text = "\n".join(
                f"- [{f.source_agent} d={f.depth} conf={f.confidence:.1f}] {f.claim}: {f.evidence[:200]}"
                for f in all_findings
            )
            payload = f"# Research findings ({len(all_findings)} total)\n{findings_text}\n\n# Cross-check\n{cross_report.model_dump_json(indent=2)}\n"
            if paper:
                payload += f"\n# Previous draft (quality={paper.quality_score:.2f})\nFill gaps:\n"
                payload += "".join(f"  - [{g.priority}] {g.section}: {g.description}\n" for g in paper.gaps)

            writer = Agent("paper_writer", prompt=PAPER_WRITER, config=self.config, response_schema=PromptedSchema(PaperDraft))
            reply = await writer.ask(payload, stream=self.flow.streams[f"paper_{iteration}"])
            paper = await reply.content(retries=1) or PaperDraft(
                title="Research", abstract="Generation failed.", body_markdown=reply.body or "", quality_score=0.0,
            )
            self._record(PaperDrafted(iteration=iteration, quality=paper.quality_score, gaps=len(paper.gaps)))

            if paper.quality_score >= self.paper_quality_threshold:
                break
            high_gaps = [g for g in paper.gaps if g.priority == "high"]
            if not high_gaps or iteration == self.paper_max_iterations - 1:
                break

            for gap in high_gaps:
                await self._send_to_bus(PaperGapEvent(
                    section=gap.section, description=gap.description,
                    research_question=gap.research_question, priority=gap.priority,
                ))
            while self._active_tasks:
                await asyncio.gather(*self._active_tasks, return_exceptions=True)

        return paper

    # -- Main -----------------------------------------------------------------

    async def run(self, topic: str) -> PaperDraft:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic is empty")

        self.flow.new_stream(FindingEmitted, name="findings")
        self.flow.new_stream(FindingEmitted.novelty > self.novelty_threshold, name="high_novelty")

        root_id = uuid.uuid4().hex[:12]
        self._record(TopicSeen(normalized=topic.lower()[:40]))
        self._record(NodeRegistered(
            node_id=root_id, topic=topic, depth=0,
            stream_name=f"team_d0_{uuid.uuid4().hex[:6]}",
        ))

        bus = self.flow.streams["bus"]
        watchers = [
            (EventWatch(FindingEmitted), self._on_finding),
            (EventWatch(DepthRequested), self._on_depth_request),
            (EventWatch(PaperGapEvent), self._on_paper_gap),
        ]
        for watch, handler in watchers:
            watch.arm(bus, handler)
            self._watches.append(watch)

        try:
            await self._run_team(build_node_instruction(topic, 0, self.max_depth), depth=0, node_id=root_id)

            while self._active_tasks:
                await asyncio.gather(*self._active_tasks, return_exceptions=True)

            cross_report = await self._run_cross_check()
            paper = await self._run_paper_loop(cross_report)

            self._record(ExplorationComplete(
                total_nodes=len(self.flow.items.by_type(NodeRegistered)),
                total_findings=len(self.flow.items.by_type(FindingEmitted)),
                max_depth=self._current_max_depth(),
                paper_quality=paper.quality_score,
            ))
            return paper
        finally:
            for w in self._watches:
                if w.is_armed:
                    w.disarm()
            self._watches.clear()

    def _spawn(self, coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)
        return task

    @property
    def urls(self) -> dict[str, str]:
        return {u.title: u.url for u in self.flow.items.by_type(UrlCaptured)}


async def research(
    topic: str, *, model: str = "gpt-5.4-mini", max_depth: int = 3,
    on_event: SSECallback | None = None, **kwargs: Any,
) -> PaperDraft:
    engine = ResearchEngine(model=model, max_depth=max_depth, on_event=on_event, **kwargs)
    return await engine.run(topic)
