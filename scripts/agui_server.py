#!/usr/bin/env python3
"""lionag2 AG-UI SSE server — FastAPI + hand-rolled SSE.

Endpoints:
  POST /api/explore           Run recursive multi-agent exploration (SSE stream)
  GET  /api/explore/config    Default agent roster + exploration config
  GET  /api/tools             List available khive tool schemas
  GET  /health                Health check

Usage:
  cd /Users/lion/projects/libs/opensrc/lionag2
  uv run python scripts/agui_server.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv

# Env + path setup before lionag2 imports
_SCRIPTS_DIR = Path(__file__).parent
_ROOT_DIR = _SCRIPTS_DIR.parent

load_dotenv(_ROOT_DIR / ".env")
load_dotenv("/Users/lion/projects/hackathon-fordham/.env")

sys.path.insert(0, str(_ROOT_DIR / "src"))

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("autogen").setLevel(logging.WARNING)
logging.getLogger("autogen.oai.client").setLevel(logging.ERROR)

# noqa: E402 — sys.path + env must be set first
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from khive._core.tools import list_tools, to_openai_tools  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

app = FastAPI(title="lionag2", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse_line(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _keepalive_task(queue: asyncio.Queue, interval: float = 15.0) -> None:
    while True:
        await asyncio.sleep(interval)
        await queue.put(": keepalive\n\n")


async def _drain_queue(queue: asyncio.Queue, sentinel: object) -> AsyncGenerator[str, None]:
    while True:
        item = await queue.get()
        if item is sentinel:
            break
        if isinstance(item, str) and item.startswith(":"):
            yield item
        else:
            yield _sse_line(item)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AgentRoleConfig(BaseModel):
    name: str
    role: str
    tools: list[str]
    system_prompt: str = ""


class ExploreRequest(BaseModel):
    topic: str = Field(..., description="Research question to explore recursively")
    max_depth: int = Field(default=4, ge=1, le=100)
    max_concurrent: int = Field(default=8, ge=1, le=16)
    services: list[str] = Field(default=["memory", "communication"])
    agents: list[AgentRoleConfig] | None = Field(
        default=None,
        description="Custom agent roster. If None, uses the default 6-agent team.",
    )
    model: str = Field(default="google/gemini-3-flash-preview")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/explore/config")
async def explore_config_endpoint():
    """Return the default agent roster and exploration config."""
    from lionag2.explore import ExplorationConfig

    config = ExplorationConfig()
    return {
        "agents": [
            {"name": a.name, "role": a.role, "tools": a.tools, "system_prompt": a.system_prompt}
            for a in config.agents
        ],
        "max_depth": config.max_depth,
        "max_concurrent": config.max_concurrent,
        "services": config.services,
        "model": config.model,
    }


@app.post("/api/explore")
async def explore_endpoint(req: ExploreRequest) -> StreamingResponse:
    """Run recursive self-exploratory research and stream events via SSE."""
    from lionag2.explore import AgentRole, ExplorationConfig, run_exploration

    explore_config = ExplorationConfig(
        max_depth=req.max_depth,
        max_concurrent=req.max_concurrent,
        services=req.services,
        model=req.model,
    )
    if req.agents:
        explore_config.agents = [
            AgentRole(
                name=a.name,
                role=a.role,
                tools=a.tools,
                system_prompt=a.system_prompt or f"You are {a.name}, a {a.role}.",
            )
            for a in req.agents
        ]

    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    async def generate() -> AsyncGenerator[str, None]:
        async def _run():
            try:
                await run_exploration(
                    topic=req.topic,
                    queue=queue,
                    config=explore_config,
                )
            except Exception as exc:
                logger.exception("Exploration error")
                await queue.put({"type": "error", "message": str(exc)})
            finally:
                await queue.put(sentinel)

        task = asyncio.create_task(_run())
        keepalive = asyncio.create_task(_keepalive_task(queue))

        try:
            async for chunk in _drain_queue(queue, sentinel):
                yield chunk
        finally:
            keepalive.cancel()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/tools")
async def tools_endpoint(services: str = "memory,communication,graph") -> dict:
    """Return available khive tool schemas grouped by service."""
    svc_list = [s.strip() for s in services.split(",") if s.strip()]
    tool_schemas = to_openai_tools(services=svc_list)
    tool_names = list_tools(services=svc_list)
    return {
        "services": svc_list,
        "tools": [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "service": t["function"]["name"].split("_")[0],
            }
            for t in tool_schemas
        ],
        "count": len(tool_names),
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "agui_server:app",
        host="0.0.0.0",
        port=8765,
        reload=False,
    )
