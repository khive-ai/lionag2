"""Server — ag-ui protocol over AG2's AGUIStream.

AG2's AGUIStream handles all event mapping (tool calls, model responses,
task lifecycle → ag-ui SSE events). We just wire our coordinator agent
into it.

Compatible with CopilotKit, Vercel AI SDK, and any ag-ui frontend.

Usage:
  uvicorn lionag2.server:app
  # or
  lionag2-server --port 8000
"""

import os
from typing import Any

from autogen.beta import Agent, KnowledgeConfig, PromptedSchema
from autogen.beta.ag_ui import AGUIStream
from autogen.beta.compact import CompactTrigger, TailWindowCompact
from autogen.beta.config import OpenAIConfig
from autogen.beta.knowledge import MemoryKnowledgeStore
from autogen.beta.policies import ConversationPolicy
from autogen.beta.tools import ExaToolkit, SandboxCodeTool
from autogen.beta.tools.subagents import persistent_stream
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..core import SafeSlidingWindowPolicy
from ..tools import KhiveKnowledgeStore, KhiveToolkit, khive_available
from .models import ExplorationResult
from .prompts import CONNECTOR, build_roster
from .tools import EMISSION_TOOLS


def _build_coordinator(
    *,
    model: str = "gpt-5.4-mini",
    api_key: str | None = None,
    base_url: str | None = None,
    extra_specialists: list[dict[str, Any]] | None = None,
    khive_api_key: str | None = None,
    khive_namespace: str = "lionag2",
) -> Agent:
    """Build the full coordinator agent with specialists as tools."""
    config_kw: dict[str, Any] = {}
    key = api_key or os.getenv("OPENAI_API_KEY")
    if key:
        config_kw["api_key"] = key
    if base_url:
        config_kw["base_url"] = base_url
    config = OpenAIConfig(model, **config_kw)

    # Knowledge store
    has_khive = khive_available() and (khive_api_key or os.getenv("KHIVE_API_KEY"))
    if has_khive:
        store = KhiveKnowledgeStore(api_key=khive_api_key, namespace=khive_namespace)
    else:
        store = MemoryKnowledgeStore()

    knowledge = KnowledgeConfig(
        store=store,
        compact=TailWindowCompact(target=30),
        compact_trigger=CompactTrigger(max_events=50),
    )

    # Tools
    exa = ExaToolkit() if os.getenv("EXA_API_KEY") else None
    sandbox = None
    if os.getenv("DAYTONA_API_KEY"):
        try:
            from autogen.beta.extensions.daytona import DaytonaCodeEnvironment

            sandbox = SandboxCodeTool(DaytonaCodeEnvironment(image="python:3.12"))
        except ImportError:
            pass

    khive_toolkit = None
    if has_khive:
        khive_toolkit = KhiveToolkit(api_key=khive_api_key, namespace=khive_namespace)

    def resolve_tools(tags: tuple[str, ...]) -> list:
        available: dict[str, Any] = {}
        if exa:
            available["search"] = exa
            available["fetch"] = exa
        if sandbox:
            available["run_code"] = sandbox
        tools = []
        seen = set()
        for tag in tags:
            if tag in available and id(available[tag]) not in seen:
                tools.append(available[tag])
                seen.add(id(available[tag]))
        tools.extend(EMISSION_TOOLS)
        if khive_toolkit:
            tools.append(khive_toolkit)
        return tools

    # Build specialist agents
    has_exa = exa is not None
    roster = build_roster(bool(has_khive), has_exa)
    if extra_specialists:
        roster.extend(extra_specialists)
    if has_khive:
        roster.append(CONNECTOR)

    sf = persistent_stream()
    specialist_tools = []
    for spec in roster:
        agent_config = config
        if spec.get("model"):
            agent_config = OpenAIConfig(spec["model"], **config_kw)

        agent = Agent(
            spec["name"],
            prompt=spec["prompt"],
            config=agent_config,
            tools=resolve_tools(spec["tools"]),
            variables={"agent_name": spec["name"], "role": spec["role"]},
            knowledge=knowledge,
            assembly=[
                ConversationPolicy(),
                SafeSlidingWindowPolicy(max_events=40, transparent=True),
            ],
        )
        specialist_tools.append(
            agent.as_tool(
                description=f"{spec['role']}. Delegate: {spec['name']}.",
                stream=sf,
            )
        )

    # Coordinator
    return Agent(
        "coordinator",
        prompt=(
            "You coordinate a recursive research team. "
            "Delegate to specialists in order. Skip only if irrelevant. "
            "Your final response must be a structured ExplorationResult.\n\n"
            "Available specialists: " + ", ".join(s["name"] for s in roster)
        ),
        config=config,
        tools=specialist_tools,
        knowledge=knowledge,
        assembly=[
            ConversationPolicy(),
            SafeSlidingWindowPolicy(max_events=60, transparent=True),
        ],
        response_schema=PromptedSchema(ExplorationResult),
    )


# ---------------------------------------------------------------------------
# ASGI app via ag-ui
# ---------------------------------------------------------------------------


_coordinator: Agent | None = None


def _get_coordinator() -> Agent:
    global _coordinator
    if _coordinator is None:
        _coordinator = _build_coordinator()
    return _coordinator


def _get_agui_stream() -> AGUIStream:
    return AGUIStream(_get_coordinator())


async def agui_endpoint(request: Request):
    """ag-ui protocol endpoint — handles RunAgentInput, streams ag-ui events."""
    stream = _get_agui_stream()
    endpoint_cls = stream.build_asgi()
    endpoint = endpoint_cls(request.scope)
    return await endpoint.post(request)


async def health(request: Request):
    return JSONResponse(
        {
            "status": "ok",
            "khive": bool(os.getenv("KHIVE_API_KEY")),
            "exa": bool(os.getenv("EXA_API_KEY")),
            "daytona": bool(os.getenv("DAYTONA_API_KEY")),
        }
    )


async def research_sse(request: Request):
    """SSE endpoint that wraps ResearchEngine.run() — streams engine events for the tree UI."""
    import asyncio
    import json

    from starlette.responses import StreamingResponse

    from .engine import ResearchEngine

    body = await request.json()
    topic = body.get("topic", "").strip()
    if not topic:
        return JSONResponse({"error": "topic is required"}, status_code=400)

    max_depth = body.get("max_depth", 2)
    model = body.get("model", "gpt-5.4-mini")

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    def on_event(event: dict) -> None:
        queue.put_nowait(event)

    engine = ResearchEngine(
        model=model,
        max_depth=max_depth,
        on_event=on_event,
    )

    async def run_and_signal():
        try:
            await engine.run(topic)
        except Exception as exc:
            queue.put_nowait({"type": "error", "message": str(exc)})
        finally:
            queue.put_nowait(None)

    async def event_stream():
        task = asyncio.create_task(run_and_signal())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app = Starlette(
    routes=[
        Route("/", agui_endpoint, methods=["POST"]),
        Route("/api/research", research_sse, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def serve() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="lionag2 research server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--model", default="gpt-5.4-mini")
    args = parser.parse_args()

    global _coordinator
    _coordinator = _build_coordinator(model=args.model)

    uvicorn.run(
        "lionag2.research.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
