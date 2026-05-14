"""Generic event-driven multi-agent engine.

Provides the domain-agnostic machinery for tree-structured, multi-agent
exploration pipelines:

  - Agent construction from spec dicts
  - Sequential team execution with handoff-based turn management
  - Depth-node spawning with dedup and concurrency control
  - Flow-based event recording and SSE notification
  - Conversation export

Domain logic (which agents, what events they emit, what observers react,
what post-processing runs) belongs in subclasses.  ResearchEngine is the
first — but any tree-shaped multi-agent workflow fits this frame.

Subclass contract:
  resolve_tools(tool_tags)  — map tool tag tuples to toolkit instances
  make_agent(spec, ...)     — create Agent, wire domain-specific observers
  _run_node(topic, ...)     — run a single exploration node (build roster + instruction)
  run(topic)                — full pipeline lifecycle
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any

from autogen.beta import Agent, KnowledgeConfig
from autogen.beta.compact import CompactTrigger, TailWindowCompact
from autogen.beta.config import OpenAIConfig
from autogen.beta.events import BaseEvent, Field
from autogen.beta.knowledge import MemoryKnowledgeStore
from autogen.beta.policies import ConversationPolicy

from .core import Flow, SafeSlidingWindowPolicy

logger = logging.getLogger("lionag2.engine")
SSECallback = Callable[[dict[str, Any]], Any]


# ---------------------------------------------------------------------------
# Engine-level events (generic across all pipelines)
# ---------------------------------------------------------------------------


class TopicSeen(BaseEvent):
    """Normalized topic registered for dedup."""

    normalized: str
    node_id: str = ""


class NodeRegistered(BaseEvent):
    """A tree node was created."""

    node_id: str
    topic: str
    depth: int = 0
    parent_node_id: str = ""
    stream_name: str = ""


class TeamStarted(BaseEvent):
    node_id: str
    agents: list = Field(default_factory=list)
    depth: int = 0


class HandoffRequested(BaseEvent):
    __transient__ = True
    next_agent: str
    reason: str = ""


class UrlCaptured(BaseEvent):
    __transient__ = True
    title: str
    url: str


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class Engine:
    """Event-driven multi-agent engine base.

    Architecture:
        - Each agent gets per-stream isolation for AG2 turns
        - Subclass wires bridge observers on agents to capture domain events
        - Engine coordinates depth expansion and quiescence
        - Flow holds all events in a shared Pile with typed progressions
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5.4-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        max_depth: int = 3,
        max_concurrent: int = 5,
        knowledge_store: Any | None = None,
        knowledge_compact_target: int = 30,
        knowledge_compact_trigger: int = 50,
        on_event: SSECallback | None = None,
    ) -> None:
        import os

        config_kw: dict[str, Any] = {}
        key = api_key or os.getenv("OPENAI_API_KEY")
        if key:
            config_kw["api_key"] = key
        if base_url:
            config_kw["base_url"] = base_url
        self.config = OpenAIConfig(model, **config_kw)

        self.max_depth = max_depth
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self.on_event = on_event

        self._knowledge_store = knowledge_store or MemoryKnowledgeStore()
        self._knowledge_config = KnowledgeConfig(
            store=self._knowledge_store,
            compact=TailWindowCompact(target=knowledge_compact_target),
            compact_trigger=CompactTrigger(max_events=knowledge_compact_trigger),
        )

        self.flow = Flow(name="engine")
        self._active_tasks: set[asyncio.Task] = set()
        self._pending_coros: deque[Any] = deque()

    # -- Recording / notification ---------------------------------------------

    def _record(self, event: BaseEvent) -> None:
        self.flow.include(event)
        if self.on_event:
            d = event.to_dict()
            d["type"] = type(event).__name__
            self.on_event(d)

    def _notify(self, kind: str, **data: Any) -> None:
        if self.on_event:
            self.on_event({"type": kind, **data})

    # -- Task management ------------------------------------------------------

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
        while self._pending_coros:
            coro = self._pending_coros.popleft()
            task = asyncio.create_task(coro)
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)

    async def _wait_for_quiescence(self) -> None:
        while self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

    # -- Tree helpers ---------------------------------------------------------

    def _topic_seen(self, normalized: str) -> bool:
        return any(ts.normalized == normalized for ts in self.flow.items[TopicSeen])

    def _current_max_depth(self) -> int:
        nodes = self.flow.items[NodeRegistered]
        return max((n.depth for n in nodes), default=0)

    # -- Agent construction ---------------------------------------------------

    def resolve_tools(self, tool_tags: tuple[str, ...]) -> list:
        """Map tool tag tuples to toolkit instances. Override per pipeline."""
        return []

    def make_agent(self, spec: dict[str, Any], *, depth: int = 0, node_id: str = "") -> Agent:
        """Create an Agent from a spec dict. Override to add domain observers."""
        tools = self.resolve_tools(spec["tools"])

        if spec.get("model"):
            config_kw: dict[str, Any] = {}
            if self.config.api_key:
                config_kw["api_key"] = self.config.api_key
            agent_config = OpenAIConfig(spec["model"], **config_kw)
        else:
            agent_config = self.config

        return Agent(
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

    # -- Team execution -------------------------------------------------------

    async def run_team(
        self,
        roster: list[dict[str, Any]],
        instruction: str,
        *,
        team_name: str,
        depth: int = 0,
        node_id: str = "",
        carry_instruction: bool = False,
    ) -> str:
        """Run sequential agents with handoff-based turn management.

        Each agent in the roster gets a turn. Agents can use the handoff()
        tool to specify who goes next, or 'done' to end the team.

        If carry_instruction is True, every agent sees the original instruction
        plus previous analysis — useful when the instruction IS the artifact
        being analyzed (e.g., code review).
        """
        self._record(
            TeamStarted(node_id=node_id, agents=[s["name"] for s in roster], depth=depth)
        )
        roster_by_name = {s["name"]: s for s in roster}
        available = ", ".join(roster_by_name.keys())

        last_reply = ""
        current_idx = 0
        max_turns = len(roster) * 2

        for turn_num in range(max_turns):
            if current_idx >= len(roster):
                break
            spec = roster[current_idx]
            agent = self.make_agent(spec, depth=depth, node_id=node_id)

            if turn_num == 0:
                turn = f"{instruction}\n\nAvailable specialists for handoff: {available}, or 'done' to end."
            elif carry_instruction:
                turn = f"{instruction}\n\n# Previous specialist analysis\n{last_reply}\n\nAvailable for handoff: {available}, or 'done'."
            else:
                turn = f"Building on previous work, continue:\n\n{last_reply}\n\nAvailable for handoff: {available}, or 'done'."
            self._notify("agent_start", node_id=node_id, agent=spec["name"])

            next_agent = [None]

            @agent.observer(HandoffRequested)
            def _on_handoff(event: HandoffRequested, _out=next_agent) -> None:
                _out[0] = event.next_agent

            try:
                reply = await agent.ask(
                    turn,
                    stream=self.flow.streams[f"{team_name}_{spec['name']}_{turn_num}"],
                )
                last_reply = reply.body or ""
                self._notify(
                    "agent_done",
                    node_id=node_id,
                    agent=spec["name"],
                    chars=len(last_reply),
                )
            except Exception as exc:
                if "role 'tool'" in str(exc):
                    stream_key = f"{team_name}_{spec['name']}_{turn_num}"
                    hist = (
                        self.flow.progression_items(stream_key)
                        if stream_key in self.flow._progressions
                        else []
                    )
                    logger.error(
                        "Orphaned tool result in %s (turn %d, %d events): %s",
                        spec["name"],
                        turn_num,
                        len(hist),
                        [type(e).__name__ for e in hist],
                    )
                logger.error("Agent %s failed: %s", spec["name"], exc)
                self._notify(
                    "agent_error", node_id=node_id, agent=spec["name"], error=str(exc)
                )
                last_reply = f"[{spec['name']} failed: {exc}]"

            self._drain_pending()

            if next_agent[0] == "done":
                break
            if next_agent[0] and next_agent[0] in roster_by_name:
                current_idx = next(
                    i for i, s in enumerate(roster) if s["name"] == next_agent[0]
                )
            else:
                current_idx += 1

        return last_reply

    # -- Depth expansion ------------------------------------------------------

    async def spawn_depth_node(
        self, topic: str, depth: int, parent_node_id: str = ""
    ) -> None:
        """Spawn a child exploration node with dedup and concurrency control."""
        if depth > self.max_depth:
            return
        normalized = topic.strip().lower()
        if self._topic_seen(normalized):
            return

        async with self._semaphore:
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
            await self._run_node(
                topic,
                depth=depth,
                team_name=team_name,
                node_id=child_id,
                parent_node_id=parent_node_id,
            )

    async def _run_node(
        self,
        topic: str,
        *,
        depth: int,
        team_name: str,
        node_id: str,
        parent_node_id: str,
    ) -> str:
        """Run a single exploration node. Override for domain-specific team setup."""
        raise NotImplementedError(
            "Subclass must implement _run_node to build roster + instruction and call run_team"
        )

    # -- Utility --------------------------------------------------------------

    @property
    def urls(self) -> dict[str, str]:
        return {u.title: u.url for u in self.flow.items.by_type(UrlCaptured)}

    def export_conversations(self) -> dict[str, list[dict[str, str]]]:
        """Extract per-agent conversations from flow progressions."""
        from autogen.beta.events.tool_events import ToolCallsEvent, ToolResultsEvent

        convos: dict[str, list[dict[str, str]]] = {}
        for pname in self.flow.progression_names:
            if (
                not pname.startswith("team_")
                and pname not in ("cross_check",)
                and not pname.startswith("paper_")
            ):
                continue
            messages: list[dict[str, str]] = []
            for ev in self.flow[pname]:
                ev_type = type(ev).__name__
                if ev_type == "ModelRequest":
                    for part in getattr(ev, "parts", []):
                        text = getattr(part, "content", None) or str(part)
                        if text:
                            messages.append({"role": "user", "content": text})
                elif ev_type == "ModelResponse":
                    for part in getattr(ev, "parts", []):
                        text = getattr(part, "content", None) or str(part)
                        if text:
                            messages.append({"role": "assistant", "content": text})
                elif isinstance(ev, ToolCallsEvent):
                    for call in ev.calls:
                        messages.append(
                            {
                                "role": "tool_call",
                                "content": f"{call.name}({call.arguments})",
                            }
                        )
                elif isinstance(ev, ToolResultsEvent):
                    for r in ev.results:
                        result = getattr(r, "result", None)
                        text = ""
                        if result:
                            for part in getattr(result, "parts", []):
                                text += getattr(part, "content", str(part))
                        messages.append(
                            {
                                "role": "tool_result",
                                "content": text or "(empty)",
                            }
                        )
            if messages:
                convos[pname] = messages
        return convos

    def save_conversations(self, path: str) -> None:
        """Save conversations as readable markdown."""
        convos = self.export_conversations()
        lines = ["# Conversations\n\n"]
        for pname, messages in convos.items():
            lines.append(f"## {pname}\n\n")
            for msg in messages:
                role = msg["role"]
                content = msg["content"]
                if role == "user":
                    lines.append(f"**User:**\n{content}\n\n")
                elif role == "assistant":
                    lines.append(f"**Assistant:**\n{content}\n\n")
                elif role == "tool_call":
                    lines.append(f"**Tool call:** `{content}`\n\n")
                elif role == "tool_result":
                    lines.append(f"**Tool result:**\n```\n{content}\n```\n\n")
            lines.append("---\n\n")

        with open(path, "w") as f:
            f.writelines(lines)

    # -- Pipeline lifecycle ---------------------------------------------------

    async def run(self, topic: str) -> Any:
        """Execute the full pipeline. Override for domain-specific stages."""
        raise NotImplementedError("Subclass must implement run()")
