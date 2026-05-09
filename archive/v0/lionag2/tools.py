"""khive MCP tools for AG2 agents.

Connects AG2 agents to khive services via MCP. No wrapping —
AG2's native MCP support handles tool discovery and execution.

Usage:
    # In a GroupChat or beta.Agent flow:
    async with khive_mcp(namespace="flow:research-42") as toolkit:
        toolkit.register_for_llm(agent)
        toolkit.register_for_execution(agent)

    # Or get the toolkit for manual registration:
    async with khive_mcp() as toolkit:
        tools = toolkit.tools  # list of Tool objects
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "khive_mcp",
    "khive_mcp_config",
    "register_khive_tools",
]


def khive_mcp_config(
    *,
    namespace: str = "shared",
    server_command: str | None = None,
    server_url: str | None = None,
) -> dict[str, Any]:
    """Build MCP server config for khive.

    Two modes:
    - stdio: spawns khived as subprocess (local)
    - SSE: connects to remote khive MCP server (Fly.io, sandbox)

    Returns config dict suitable for mcp.StdioServerParameters or SSE.
    """
    if server_url:
        return {
            "transport": "sse",
            "url": server_url,
            "namespace": namespace,
        }

    command = server_command or "khived"
    return {
        "transport": "stdio",
        "command": command,
        "args": ["mcp", "start", "--namespace", namespace],
        "env": {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        },
    }


@asynccontextmanager
async def khive_mcp(
    *,
    namespace: str = "shared",
    server_command: str | None = None,
    server_url: str | None = None,
    use_tools: bool = True,
    use_resources: bool = False,
):
    """Context manager that yields an AG2 Toolkit connected to khive MCP.

    Usage:
        async with khive_mcp(namespace="flow:42") as toolkit:
            toolkit.register_for_llm(agent)
            toolkit.register_for_execution(agent)
    """
    from autogen.mcp import create_toolkit

    config = khive_mcp_config(
        namespace=namespace,
        server_command=server_command,
        server_url=server_url,
    )

    if config["transport"] == "stdio":
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env"),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                toolkit = await create_toolkit(
                    session,
                    use_mcp_tools=use_tools,
                    use_mcp_resources=use_resources,
                )
                logger.info(
                    "Connected to khive MCP (stdio, namespace=%s): %d tools",
                    namespace,
                    len(toolkit.tools),
                )
                yield toolkit

    elif config["transport"] == "sse":
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with sse_client(url=config["url"]) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                toolkit = await create_toolkit(
                    session,
                    use_mcp_tools=use_tools,
                    use_mcp_resources=use_resources,
                )
                logger.info(
                    "Connected to khive MCP (SSE, namespace=%s, url=%s): %d tools",
                    namespace,
                    config["url"],
                    len(toolkit.tools),
                )
                yield toolkit
    else:
        raise ValueError(f"Unknown transport: {config['transport']}")


async def register_khive_tools(
    agents: list,
    executor,
    *,
    namespace: str = "shared",
    server_command: str | None = None,
    server_url: str | None = None,
    tool_filter: list[str] | None = None,
):
    """Register khive MCP tools on multiple AG2 agents.

    If tool_filter is set, only tools whose names contain any of the
    filter strings are registered. This enables per-agent tool scoping:

        # Researcher gets memory + search
        await register_khive_tools(
            [researcher], executor,
            tool_filter=["memory", "recall", "search"],
        )

        # Analyst gets memory + work
        await register_khive_tools(
            [analyst], executor,
            tool_filter=["memory", "work", "store"],
        )
    """
    from autogen import register_function

    async with khive_mcp(
        namespace=namespace,
        server_command=server_command,
        server_url=server_url,
    ) as toolkit:
        for tool in toolkit.tools:
            if tool_filter:
                if not any(f in tool.name for f in tool_filter):
                    continue
            for agent in agents:
                tool.register_for_llm(agent)
                tool.register_for_execution(executor)
                logger.info("Registered tool %r on agent %r", tool.name, agent.name)
