#!/usr/bin/env python3
"""lionag2 AG-UI SSE server — FastAPI + hand-rolled SSE.

Two transport approaches live side-by-side:
  Approach 2 (primary): Hand-rolled SSE generator wired to the lionag2
  pipeline via asyncio.Queue callbacks.  Simple, reliable, frontend-
  compatible via EventSource.

Endpoints:
  POST /api/research          Run live research flow (SSE stream)
  GET  /api/replay/{slug}     Replay a saved demo (SSE stream)
  GET  /api/demos             List available saved demo slugs
  GET  /api/tools             List available khive tool schemas

Usage:
  cd /Users/lion/projects/libs/opensrc/lionag2
  uv run python scripts/agui_server.py
  # or: uv run uvicorn scripts.agui_server:app --reload --port 8765
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, AsyncGenerator

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Env + path setup (must happen before lionag2 imports)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).parent
_ROOT_DIR = _SCRIPTS_DIR.parent

load_dotenv(_ROOT_DIR / ".env")
load_dotenv("/Users/lion/projects/hackathon-fordham/.env")

sys.path.insert(0, str(_ROOT_DIR / "src"))
# Ensure scripts/ is on sys.path so demo_showcase can be imported directly
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Suppress noisy loggers before importing libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("autogen").setLevel(logging.WARNING)
logging.getLogger("autogen.oai.client").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# FastAPI imports (E402: intentional — sys.path + env must be set first)
# ---------------------------------------------------------------------------

import lionagi as li  # noqa: E402
from demo_showcase import DEMOS, run_team  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from khive._core.tools import list_tools, to_openai_tools  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from lionag2.models import ResearchPlan  # noqa: E402

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="lionag2 Demo Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)

DATA_DIR = _ROOT_DIR / "data" / "demos"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(text: str) -> str:
    import re
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")[:60]
    return slug

# ---------------------------------------------------------------------------
# Agent budget guidance (enforces 2-3 teams, 2-3 agents each, no synthesis team)
# ---------------------------------------------------------------------------

GUIDANCE = (
    "Design 2-3 parallel research teams with 2-3 agents each. "
    "Agent names must be single words with NO spaces. "
    "No synthesis team — synthesis happens externally."
)


# ---------------------------------------------------------------------------
# Cross-team knowledge sharing + harness tracking
# ---------------------------------------------------------------------------


class SharedKnowledge:
    """Cross-team knowledge store with khive-named tool functions.

    Uses khive tool naming conventions (memory_remember / memory_recall /
    communication_send / communication_list) for consistency with the real
    khive API, while keeping a local in-process implementation for demos.
    Logs every call for SSE event emission.
    """

    def __init__(self, services: list[str] | None = None):
        self.services = services or ["memory", "communication"]
        self.findings: dict[str, str] = {}
        self.tool_log: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []  # cross-team communication log

    # ------------------------------------------------------------------
    # memory service tools
    # ------------------------------------------------------------------

    def memory_remember(self, content: str, memory_type: str = "semantic") -> str:
        """Store a new memory (khive memory.remember)."""
        key = f"mem_{len(self.findings)}"
        self.findings[key] = content
        self.tool_log.append({
            "tool": "memory_remember",
            "args": {"content": content, "memory_type": memory_type},
            "timestamp": time.time(),
        })
        return f"Stored memory '{key}' (type={memory_type})"

    def memory_recall(self, query: str) -> str:
        """Recall memories by semantic search (khive memory.recall)."""
        if not self.findings:
            self.tool_log.append({
                "tool": "memory_recall",
                "args": {"query": query},
                "result": "no memories stored yet",
                "timestamp": time.time(),
            })
            return "No memories stored yet."
        matches = []
        q = query.lower()
        for k, v in self.findings.items():
            if q in k.lower() or q in v.lower() or not q:
                matches.append(f"[{k}]: {v}")
        result = "\n".join(matches) if matches else "No matching memories."
        self.tool_log.append({
            "tool": "memory_recall",
            "args": {"query": query},
            "result": result,
            "timestamp": time.time(),
        })
        return result

    # ------------------------------------------------------------------
    # communication service tools
    # ------------------------------------------------------------------

    def communication_send(
        self, to_lambda: str, content: str, subject: str = ""
    ) -> str:
        """Send a message to another team (khive communication.send)."""
        msg: dict[str, Any] = {
            "from": "agent",
            "to": to_lambda,
            "content": content,
            "subject": subject,
            "timestamp": time.time(),
        }
        self.messages.append(msg)
        self.tool_log.append({
            "tool": "communication_send",
            "args": {"to_lambda": to_lambda, "content": content, "subject": subject},
            "timestamp": time.time(),
        })
        return f"Message sent to '{to_lambda}'"

    def communication_list(self, status: str = "all") -> str:
        """List messages from other teams (khive communication.list)."""
        if not self.messages:
            self.tool_log.append({
                "tool": "communication_list",
                "args": {"status": status},
                "result": "no messages",
                "timestamp": time.time(),
            })
            return "No messages."
        result = "\n".join(
            f"[{m['from']} → {m['to']}] {m.get('subject', '')} | {m['content']}"
            for m in self.messages
        )
        self.tool_log.append({
            "tool": "communication_list",
            "args": {"status": status},
            "result": result,
            "timestamp": time.time(),
        })
        return result

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def get_tool_registry(self) -> dict[str, Any]:
        registry: dict[str, Any] = {}

        def _wrap(method):
            """AG2 register_function rejects bound methods — wrap as plain function."""
            import functools

            @functools.wraps(method)
            def wrapper(*args, **kwargs):
                return method(*args, **kwargs)

            return wrapper

        if "memory" in self.services:
            registry["memory_remember"] = _wrap(self.memory_remember)
            registry["memory_recall"] = _wrap(self.memory_recall)
        if "communication" in self.services:
            registry["communication_send"] = _wrap(self.communication_send)
            registry["communication_list"] = _wrap(self.communication_list)
        return registry


def _build_agent_configs_with_tools(
    team: dict, knowledge: SharedKnowledge
) -> list[dict]:
    """Build AG2 agent configs WITH khive tool access and enhanced prompts."""
    configs = []
    names = [n.replace(" ", "_") for n in team["agent_names"]]
    roles = team["agent_roles"]
    has_deps = bool(team.get("depends_on"))
    tool_names = list(knowledge.get_tool_registry().keys())
    per_agent_tools = team.get("agent_tools", {})

    for i, (name, role) in enumerate(zip(names, roles)):
        is_last = i == len(names) - 1
        handoffs = []
        if not is_last:
            handoffs.append({
                "target": names[i + 1],
                "condition": f"When {name} has completed their analysis",
            })

        system_msg = f"You are {name}, a {role}. Be concise — max 4 sentences per turn.\n\n"
        system_msg += "You have access to khive tools:\n"
        system_msg += "- memory_remember(content, memory_type): Store a finding in persistent memory\n"
        system_msg += "- memory_recall(query): Search stored memories semantically\n"
        system_msg += "- communication_send(to_lambda, content, subject): Send message to another team\n"
        system_msg += "- communication_list(status): Read messages from other teams\n\n"

        if has_deps:
            system_msg += "IMPORTANT: Start by calling memory_recall('') to see what prior teams discovered.\n"

        if is_last:
            system_msg += "Before concluding, call memory_remember with your team's key insight. "
            system_msg += "Then summarize comprehensively and say TERMINATE."
        else:
            system_msg += f"Hand off to {names[i + 1]} when your analysis is complete."

        # Use per-agent tool list if specified, otherwise all tools
        agent_tool_list = per_agent_tools.get(name, tool_names)
        configs.append({
            "name": name,
            "role": role,
            "system_message": system_msg,
            "tools": agent_tool_list,
            "handoffs": handoffs,
        })
    return configs


async def run_team_with_tools(
    team: dict,
    knowledge: SharedKnowledge,
    context: str = "",
) -> str:
    """Run team with shared knowledge tools registered."""
    agent_configs = _build_agent_configs_with_tools(team, knowledge)
    model = li.iModel(
        provider="ag2",
        endpoint="group_chat",
        agent_configs=agent_configs,
        llm_config={
            "config_list": [{
                "model": "google/gemini-3-flash-preview",
                "api_key": os.environ.get("OPENROUTER_API_KEY", os.environ.get("GEMINI_API_KEY", "")),
                "base_url": "https://openrouter.ai/api/v1",
                "default_headers": {"HTTP-Referer": "https://khive.ai", "X-Title": "lionag2"},
            }],
        },
        tool_registry=knowledge.get_tool_registry(),
    )
    prompt = f"Team objective: {team['objective']}"
    if context:
        prompt += f"\n\nContext from prior teams:\n{context}"

    branch = li.Branch(chat_model=model)
    try:
        result = await branch.operate(instruction=prompt)
        return str(result)
    except Exception as e:
        logger.warning("Team %s GroupChat failed: %s, falling back", team["id"], e)
        fb = li.Branch(
            chat_model=li.iModel(provider="openrouter", model="google/gemini-3-flash-preview"),
            system=(
                f"You are a research team: "
                + ", ".join(
                    f"{n} ({r})"
                    for n, r in zip(team["agent_names"], team["agent_roles"])
                )
                + "."
            ),
        )
        result = await fb.communicate(instruction=prompt)
        return str(result)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ResearchRequest(BaseModel):
    topic: str = Field(..., description="Research topic to investigate")
    use_config: bool = Field(
        default=False,
        description="If true, match topic against hardcoded DEMOS config instead of calling LLM planner",
    )
    services: list[str] = Field(
        default=["memory", "communication"],
        description="khive services to enable as agent tools",
    )
    sandbox_mode: bool = Field(
        default=False,
        description="If true, run agents in Daytona sandboxes via NLIP",
    )
    config: dict | None = Field(
        default=None,
        description="Full team/agent config. If provided, overrides use_config and LLM planning.",
    )


class DemoInfo(BaseModel):
    slug: str
    topic: str
    agent_count: int
    elapsed_s: float


class DemosResponse(BaseModel):
    demos: list[DemoInfo]


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse_line(event: dict[str, Any]) -> str:
    """Encode a dict as a single SSE data line."""
    return f"data: {json.dumps(event)}\n\n"


async def _keepalive_task(queue: asyncio.Queue, interval: float = 15.0) -> None:
    """Periodically push a comment keepalive so the connection stays open."""
    while True:
        await asyncio.sleep(interval)
        await queue.put(": keepalive\n\n")  # raw SSE comment, not a data event


async def _drain_queue(
    queue: asyncio.Queue,
    sentinel: object,
) -> AsyncGenerator[str, None]:
    """Yield SSE lines from *queue* until the sentinel is received."""
    while True:
        item = await queue.get()
        if item is sentinel:
            break
        if isinstance(item, str) and item.startswith(":"):
            # Raw SSE comment (keepalive)
            yield item
        else:
            yield _sse_line(item)


# ---------------------------------------------------------------------------
# Live research pipeline
# ---------------------------------------------------------------------------


async def _run_pipeline_into_queue(
    topic: str,
    use_config: bool,
    queue: asyncio.Queue,
    sentinel: object,
    services: list[str] | None = None,
    sandbox_mode: bool = False,
    config: dict | None = None,
) -> None:
    """Execute the lionag2 research pipeline, pushing SSE events into *queue*."""
    t0 = time.time()
    sandbox_mgr = None

    try:
        # ------------------------------------------------------------------
        # Determine teams list
        # ------------------------------------------------------------------
        if config is not None:
            # Full config provided directly — override everything
            raw_teams = config["teams"]
            plan_topic = config.get("topic", topic)
        elif use_config:
            # Match on slug first (frontend sends slug when use_config=true)
            matched = next(
                (d for d in DEMOS if d["slug"] == topic.strip()),
                None,
            )
            if matched is None:
                # Fallback: match on full topic string
                matched = next(
                    (d for d in DEMOS if d["topic"].strip().lower() == topic.strip().lower()),
                    None,
                )
            if matched is None:
                await queue.put(
                    {
                        "type": "error",
                        "message": (
                            f"No hardcoded config matches topic '{topic[:80]}'. "
                            "Set use_config=false to use LLM planning."
                        ),
                    }
                )
                return

            raw_teams = matched["teams"]
            plan_topic = matched["topic"]
        else:
            # ------------------------------------------------------------------
            # LLM planning via create_plan
            # ------------------------------------------------------------------
            from lionag2.plan import create_plan

            plan: ResearchPlan = await create_plan(topic, guidance=GUIDANCE)
            raw_teams = [
                {
                    "id": t.id,
                    "name": t.name,
                    "objective": t.objective,
                    "agent_names": t.agent_names,
                    "agent_roles": t.agent_roles,
                    "depends_on": t.depends_on,
                }
                for t in plan.teams
            ]
            plan_topic = plan.topic

        # ------------------------------------------------------------------
        # Emit plan event
        # ------------------------------------------------------------------
        await queue.put(
            {
                "type": "plan",
                "topic": plan_topic,
                "teams": [
                    {
                        "id": t["id"],
                        "name": t["name"],
                        "agent_names": t["agent_names"],
                        "depends_on": t.get("depends_on", []),
                    }
                    for t in raw_teams
                ],
            }
        )

        # ------------------------------------------------------------------
        # Wave-based execution with cross-team knowledge sharing
        # ------------------------------------------------------------------
        active_services = services or ["memory", "communication"]
        knowledge = SharedKnowledge(services=active_services)
        completed: dict[str, str] = {}

        # Emit harness info
        await queue.put({
            "type": "harness",
            "services": active_services,
            "tools": list(knowledge.get_tool_registry().keys()),
            "observers": ["token_monitor"],
            "policies": ["sliding_window"],
            "timestamp": time.time(),
        })

        # ------------------------------------------------------------------
        # Optional Daytona sandbox creation (one per team, first agent only)
        # ------------------------------------------------------------------
        if sandbox_mode:
            from lionagi.providers.ag2.sandbox import SandboxManager  # lazy import

            sandbox_mgr = SandboxManager(
                model="google/gemini-3-flash-preview",
                env_vars={"OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", "")},
            )

            await queue.put({
                "type": "sandbox_creating",
                "message": "Creating Daytona sandboxes for remote agents...",
                "timestamp": time.time(),
            })

            for team in raw_teams:
                agent_names = team.get("agent_names", [])
                if not agent_names:
                    continue
                agent_name = agent_names[0]  # only first agent per team

                try:
                    sandbox_agent = await sandbox_mgr.create_agent_sandbox(
                        name=agent_name,
                        system_message=f"You are {agent_name}, a research specialist.",
                    )
                    await queue.put({
                        "type": "sandbox_ready",
                        "agent_name": agent_name,
                        "team_id": team["id"],
                        "sandbox_url": sandbox_agent.url,
                        "sandbox_id": sandbox_agent.sandbox_id,
                        "timestamp": time.time(),
                    })
                except Exception as e:
                    await queue.put({
                        "type": "sandbox_error",
                        "agent_name": agent_name,
                        "error": str(e),
                        "timestamp": time.time(),
                    })

        while len(completed) < len(raw_teams):
            wave = [
                t
                for t in raw_teams
                if t["id"] not in completed
                and all(d in completed for d in t.get("depends_on", []))
            ]
            if not wave:
                remaining = [t["id"] for t in raw_teams if t["id"] not in completed]
                await queue.put(
                    {
                        "type": "error",
                        "message": f"Deadlock: no team ready. Remaining: {remaining}",
                    }
                )
                return

            # Announce all teams in this wave
            for t in wave:
                has_deps = bool(t.get("depends_on"))
                await queue.put(
                    {
                        "type": "team_start",
                        "team_id": t["id"],
                        "team_name": t["name"],
                        "agent_names": t["agent_names"],
                        "tools": list(knowledge.get_tool_registry().keys()),
                        "has_prior_knowledge": has_deps and len(knowledge.findings) > 0,
                        "timestamp": time.time(),
                    }
                )

            # Execute wave in parallel with shared knowledge
            log_before = len(knowledge.tool_log)

            async def _exec_team(team: dict) -> tuple[str, str]:
                context = "\n\n".join(
                    f"[{dep}]: {completed[dep][:2000]}"
                    for dep in team.get("depends_on", [])
                    if dep in completed
                )
                output = await run_team_with_tools(team, knowledge, context)
                return team["id"], output

            wave_results = await asyncio.gather(*[_exec_team(t) for t in wave])

            # Emit tool call events from this wave
            new_tool_calls = knowledge.tool_log[log_before:]
            for tc in new_tool_calls:
                await queue.put({
                    "type": "tool_call",
                    "tool": tc["tool"],
                    "args": tc["args"],
                    "result": tc.get("result"),
                    "timestamp": tc["timestamp"],
                })

            # Emit communication events from this wave
            msgs_before_wave = len(knowledge.messages) - sum(
                1 for tc in new_tool_calls if tc["tool"] == "communication_send"
            )
            new_messages = knowledge.messages[msgs_before_wave:]
            for msg in new_messages:
                await queue.put({
                    "type": "communication",
                    "from_team": msg["from"],
                    "to_team": msg["to"],
                    "content": msg["content"][:100],
                    "subject": msg.get("subject", ""),
                    "timestamp": msg["timestamp"],
                })

            for tid, output in wave_results:
                completed[tid] = output
                await queue.put(
                    {
                        "type": "team_done",
                        "team_id": tid,
                        "output": output,
                        "findings_count": len(knowledge.findings),
                        "timestamp": time.time(),
                    }
                )

        # ------------------------------------------------------------------
        # Synthesis
        # ------------------------------------------------------------------
        await queue.put({"type": "synthesis_start", "timestamp": time.time()})

        synth_branch = li.Branch(
            chat_model=li.iModel(provider="openrouter", model="google/gemini-3-flash-preview"),
            system="You synthesize research team outputs into a coherent, well-structured final report.",
        )
        outputs_text = "\n\n".join(
            f"## Team: {tid}\n{out}" for tid, out in completed.items()
        )
        synthesis_result = await synth_branch.communicate(
            instruction=(
                f"Topic: {topic}\n\n"
                f"Team outputs:\n{outputs_text}\n\n"
                "Write a comprehensive final report."
            ),
        )
        synthesis_text = str(synthesis_result)

        await queue.put(
            {"type": "synthesis", "text": synthesis_text, "timestamp": time.time()}
        )

        elapsed = time.time() - t0
        agent_count = sum(len(t["agent_names"]) for t in raw_teams)

        # Auto-save to data/demos/
        slug = _slugify(topic)
        record = {
            "slug": slug,
            "topic": topic,
            "teams": raw_teams,
            "team_outputs": completed,
            "synthesis": synthesis_text,
            "elapsed_s": round(elapsed, 2),
            "agent_count": agent_count,
            "services": active_services,
            "communications": knowledge.messages,
        }
        out_path = DATA_DIR / f"{slug}.json"
        out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        logger.info("Saved demo record to %s", out_path)

        await queue.put(
            {
                "type": "done",
                "elapsed_s": round(elapsed, 2),
                "agent_count": agent_count,
                "slug": slug,
            }
        )

    except Exception as exc:
        logger.exception("Pipeline error")
        await queue.put({"type": "error", "message": str(exc)})
    finally:
        if sandbox_mode and sandbox_mgr is not None:
            sandbox_mgr.cleanup()
        await queue.put(sentinel)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/research")
async def research_endpoint(req: ResearchRequest) -> StreamingResponse:
    """Run a live research flow and stream events via SSE."""
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    async def generate() -> AsyncGenerator[str, None]:
        # Start pipeline in background; keepalive in another background task
        pipeline_task = asyncio.create_task(
            _run_pipeline_into_queue(
                req.topic, req.use_config, queue, sentinel,
                services=req.services, sandbox_mode=req.sandbox_mode,
                config=req.config,
            )
        )
        keepalive = asyncio.create_task(_keepalive_task(queue))

        try:
            async for chunk in _drain_queue(queue, sentinel):
                yield chunk
        finally:
            keepalive.cancel()
            pipeline_task.cancel()
            try:
                await pipeline_task
            except (asyncio.CancelledError, Exception) as exc:
                logger.debug("Pipeline task ended: %s", exc)

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
async def tools_endpoint(services: str = "memory,communication") -> dict:
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


@app.get("/api/config/{slug}")
async def get_config(slug: str) -> dict:
    """Return the full editable config for a preset demo."""
    matched = next((d for d in DEMOS if d["slug"] == slug), None)
    if not matched:
        raise HTTPException(status_code=404, detail=f"Preset '{slug}' not found")
    return {
        "topic": matched["topic"],
        "teams": matched["teams"],
    }


@app.get("/api/replay/{slug}")
async def replay_endpoint(slug: str) -> StreamingResponse:
    """Replay a saved demo from data/demos/{slug}.json with 500 ms delays."""
    demo_path = DATA_DIR / f"{slug}.json"
    if not demo_path.exists():
        raise HTTPException(status_code=404, detail=f"Demo '{slug}' not found")

    record = json.loads(demo_path.read_text())

    async def generate() -> AsyncGenerator[str, None]:
        teams: list[dict] = record.get("teams", [])
        team_outputs: dict[str, str] = record.get("team_outputs", {})

        # Plan event
        yield _sse_line(
            {
                "type": "plan",
                "topic": record.get("topic", slug),
                "teams": [
                    {
                        "id": t["id"],
                        "name": t["name"],
                        "agent_names": t.get("agent_names", []),
                        "depends_on": t.get("depends_on", []),
                    }
                    for t in teams
                ],
            }
        )
        await asyncio.sleep(0.5)

        # Replay team events in the original wave order
        completed: set[str] = set()

        while len(completed) < len(teams):
            wave = [
                t
                for t in teams
                if t["id"] not in completed
                and all(d in completed for d in t.get("depends_on", []))
            ]
            if not wave:
                break  # shouldn't happen with valid data

            for t in wave:
                yield _sse_line(
                    {
                        "type": "team_start",
                        "team_id": t["id"],
                        "team_name": t["name"],
                        "agent_names": t.get("agent_names", []),
                        "timestamp": time.time(),
                    }
                )
            await asyncio.sleep(0.5)

            for t in wave:
                tid = t["id"]
                output = team_outputs.get(tid, "")
                yield _sse_line(
                    {
                        "type": "team_done",
                        "team_id": tid,
                        "output": output,
                        "timestamp": time.time(),
                    }
                )
                completed.add(tid)
                await asyncio.sleep(0.5)

        # Synthesis
        yield _sse_line({"type": "synthesis_start", "timestamp": time.time()})
        await asyncio.sleep(0.5)

        yield _sse_line(
            {
                "type": "synthesis",
                "text": record.get("synthesis", ""),
                "timestamp": time.time(),
            }
        )
        await asyncio.sleep(0.5)

        yield _sse_line(
            {
                "type": "done",
                "elapsed_s": record.get("elapsed_s", 0.0),
                "agent_count": record.get("agent_count", 0),
            }
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/demos", response_model=DemosResponse)
async def list_demos() -> DemosResponse:
    """List available saved demo slugs from data/demos/."""
    infos: list[DemoInfo] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        try:
            record = json.loads(path.read_text())
            infos.append(
                DemoInfo(
                    slug=record.get("slug", path.stem),
                    topic=record.get("topic", ""),
                    agent_count=record.get("agent_count", 0),
                    elapsed_s=record.get("elapsed_s", 0.0),
                )
            )
        except Exception:
            logger.warning("Could not parse demo file: %s", path)
    return DemosResponse(demos=infos)


# ---------------------------------------------------------------------------
# Recursive exploration endpoint
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
        description="Custom agent roster. If None, uses default 3-agent team (Surveyor, Analyst, Critic).",
    )
    model: str = Field(default="google/gemini-3-flash-preview")


@app.get("/api/explore/config")
async def explore_config_endpoint():
    """Return the default agent roster and exploration config."""
    from lionag2.explore import DEFAULT_AGENTS, ExplorationConfig

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
        "available_tools": ["tavily_search", "memory_recall", "memory_remember"],
    }


@app.post("/api/explore")
async def explore_endpoint(req: ExploreRequest) -> StreamingResponse:
    """Run recursive self-exploratory research and stream events via SSE."""
    from lionag2.explore import ExplorationConfig, AgentRole, run_exploration

    # Build config from request
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


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "agui_server:app",
        host="0.0.0.0",  # noqa: S104
        port=8765,
        reload=False,
        log_level="info",
    )
