"""Research pipeline — domain logic on the generic Engine.

ResearchEngine adds:
  - Tool resolution (Exa, Daytona sandbox, khive)
  - Research-specific agent observers (findings → depth, contradictions, pivots)
  - Cross-check phase after exploration quiesces
  - Iterative paper writing with gap-triggered depth expansion
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

from autogen.beta import Agent
from autogen.beta.events import ToolResultsEvent
from autogen.beta.tools import ExaToolkit, SandboxCodeTool

from ..core import FuzzySchema
from ..engine import Engine, NodeRegistered, SSECallback, TopicSeen, UrlCaptured
from ..tools import KhiveToolkit, khive_available
from .events import (
    ContradictionFound,
    CrossCheckDone,
    DepthRequested,
    ExplorationComplete,
    FindingEmitted,
    PaperDrafted,
    PaperGapEvent,
    PivotDetected,
)
from .middleware import clean_search_results
from .models import CrossCheckReport, PaperDraft
from .prompts import CONNECTOR, CROSS_CHECK, PAPER_WRITER, build_node_instruction, build_roster
from .tools import EMISSION_TOOLS, PAPER_TOOLS

logger = logging.getLogger("lionag2.engine")


def _paper_from_raw(raw: str) -> PaperDraft:
    """Last resort: wrap raw text as paper body when FuzzySchema also fails."""
    return PaperDraft(
        title="Research Paper",
        abstract="(structured output parsing failed)",
        body_markdown=raw,
        quality_score=0.3,
    )


class ResearchEngine(Engine):
    """Recursive research engine — extends Engine with research domain logic.

    Pipeline:
        1. Root exploration node → specialist team with handoff
        2. Reactive depth expansion (FindingEmitted with high novelty)
        3. Wait for quiescence
        4. Cross-check (contradictions, gaps, redundancies)
        5. Iterative paper writing (gaps trigger more research)
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
        sandbox_image: str = "python:3.12",
        on_event: SSECallback | None = None,
    ) -> None:
        # Khive knowledge store (if available)
        has_khive = khive_available() and bool(khive_api_key or os.getenv("KHIVE_API_KEY"))
        if has_khive:
            from ..tools import KhiveKnowledgeStore

            knowledge_store = KhiveKnowledgeStore(api_key=khive_api_key, namespace=khive_namespace)
        else:
            knowledge_store = None

        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_depth=max_depth,
            max_concurrent=max_concurrent,
            knowledge_store=knowledge_store,
            on_event=on_event,
        )

        self.flow.name = "research"
        self.novelty_threshold = novelty_threshold
        self.paper_max_iterations = paper_max_iterations
        self.paper_quality_threshold = paper_quality_threshold
        self._extra_specialists = extra_specialists or []

        self._has_khive = has_khive
        self._khive_api_key = khive_api_key
        self._khive_namespace = khive_namespace

        self._sandbox: SandboxCodeTool | None = None
        try:
            from autogen.beta.extensions.docker import DockerCodeEnvironment

            self._sandbox = SandboxCodeTool(
                DockerCodeEnvironment(image=sandbox_image, network_mode="bridge")
            )
        except (ImportError, Exception) as exc:
            logger.warning("Docker sandbox unavailable: %s", exc)

    # -- Tool resolution (override) -------------------------------------------

    def resolve_tools(self, tool_tags: tuple[str, ...]) -> list:
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

    # -- Agent construction (override) ----------------------------------------

    def make_agent(self, spec: dict[str, Any], *, depth: int = 0, node_id: str = "") -> Agent:
        agent = super().make_agent(spec, depth=depth, node_id=node_id)
        engine = self

        @agent.observer(FindingEmitted)
        def _on_finding(event: FindingEmitted) -> None:
            engine._record(event)
            if event.novelty > engine.novelty_threshold and event.depth < engine.max_depth:
                engine._spawn(
                    engine.spawn_depth_node(
                        event.claim,
                        event.depth + 1,
                        node_id,
                    )
                )

        @agent.observer(DepthRequested)
        def _on_depth_req(event: DepthRequested) -> None:
            engine._record(event)
            engine._spawn(
                engine.spawn_depth_node(
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

    # -- Node execution (override) --------------------------------------------

    async def _run_node(
        self,
        topic: str,
        *,
        depth: int,
        team_name: str,
        node_id: str,
        parent_node_id: str,
    ) -> str:
        instruction = build_node_instruction(topic, depth, self.max_depth)

        if parent_node_id and depth > 0:
            parent_findings = [
                f for f in self.flow.items[FindingEmitted] if f.node_id == parent_node_id
            ]
            if parent_findings:
                prior = "\n".join(f"- [{f.source_agent}] {f.claim}" for f in parent_findings)
                instruction = f"{instruction}\n\n# Prior findings from depth {depth - 1}\n{prior}"

        has_exa = bool(os.getenv("EXA_API_KEY"))
        roster = build_roster(self._has_khive, has_exa) + self._extra_specialists
        if self._has_khive:
            roster.append(CONNECTOR)

        return await self.run_team(
            roster,
            instruction,
            team_name=team_name,
            depth=depth,
            node_id=node_id,
        )

    # -- Post-processing stages -----------------------------------------------

    async def _run_cross_check(self) -> CrossCheckReport:
        all_findings = self.flow.items.by_type(FindingEmitted)
        if not all_findings:
            return CrossCheckReport(summary="No findings to cross-check.")

        checker = Agent(
            "cross_checker",
            prompt=CROSS_CHECK,
            config=self.config,
            response_schema=FuzzySchema(CrossCheckReport),
        )
        ctx_text = "\n".join(f"- [{f.source_agent} d={f.depth}] {f.claim}" for f in all_findings)
        reply = await checker.ask(
            f"Cross-check {len(all_findings)} findings:\n{ctx_text}",
            stream=self.flow.streams["cross_check"],
        )
        try:
            report = await reply.content(retries=2) or CrossCheckReport(summary=reply.body or "")
        except Exception:
            report = CrossCheckReport(summary=reply.body or "")
        self._record(
            CrossCheckDone(contradictions=len(report.contradictions), gaps=len(report.gaps))
        )
        return report

    def _build_writer_payload(
        self,
        cross_report: CrossCheckReport,
        prev_paper: PaperDraft | None,
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
                    f'- {c.source_a}: "{c.claim_a}" vs {c.source_b}: "{c.claim_b}" '
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
                response_schema=FuzzySchema(PaperDraft),
            )

            @writer.observer(PaperGapEvent)
            def _on_gap(event: PaperGapEvent) -> None:
                engine._record(event)
                if event.priority == "high":
                    engine._spawn(
                        engine.spawn_depth_node(
                            event.research_question,
                            engine._current_max_depth() + 1,
                        )
                    )

            reply = await writer.ask(payload, stream=self.flow.streams[f"paper_{iteration}"])
            self._drain_pending()
            try:
                paper = await reply.content(retries=2) or PaperDraft(
                    title="Research",
                    abstract="Generation failed.",
                    body_markdown=reply.body or "",
                    quality_score=0.0,
                )
            except Exception:
                paper = _paper_from_raw(reply.body or "")
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

    # -- Main pipeline --------------------------------------------------------

    async def run(self, topic: str) -> PaperDraft:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic is empty")

        self.flow.new_stream(FindingEmitted, name="findings")
        self.flow.new_stream(FindingEmitted.novelty > self.novelty_threshold, name="high_novelty")

        root_id = uuid.uuid4().hex[:12]
        root_team = f"team_d0_{uuid.uuid4().hex[:6]}"
        self._record(TopicSeen(normalized=topic.strip().lower()))
        self._record(
            NodeRegistered(
                node_id=root_id,
                topic=topic,
                depth=0,
                stream_name=root_team,
            )
        )

        await self._run_node(
            topic,
            depth=0,
            team_name=root_team,
            node_id=root_id,
            parent_node_id="",
        )

        await self._wait_for_quiescence()

        cross_report = await self._run_cross_check()
        paper = await self._run_paper_loop(cross_report)

        await self._wait_for_quiescence()

        self._record(
            ExplorationComplete(
                total_nodes=len(self.flow.items.by_type(NodeRegistered)),
                total_findings=len(self.flow.items.by_type(FindingEmitted)),
                max_depth=self._current_max_depth(),
                paper_quality=paper.quality_score,
            )
        )
        return paper


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
