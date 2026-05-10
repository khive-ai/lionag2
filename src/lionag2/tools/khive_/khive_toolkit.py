"""AG2 Toolkit wrapping khive SDK as the shared research brain.

Follows ExaToolkit pattern — each method returns a FunctionTool.
Agents get cross-node memory, graph, and messaging for free.
"""

import logging
from typing import Annotated

from autogen.beta import Toolkit, ToolResult
from autogen.beta.tools import tool
from pydantic import Field

logger = logging.getLogger(__name__)


def khive_available() -> bool:
    try:
        import khive  # noqa: F401

        return True
    except ImportError:
        return False


class KhiveToolkit(Toolkit):
    """AG2 Toolkit providing khive memory, graph, and communication tools."""

    __slots__ = ("_api_key", "_base_url", "_namespace")

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        namespace: str = "default",
        services: tuple[str, ...] = ("memory", "graph", "communication"),
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._namespace = namespace

        tools = []
        svc = set(services)
        if "memory" in svc:
            tools.extend([self.memory_recall(), self.memory_remember()])
        if "graph" in svc:
            tools.extend(
                [
                    self.graph_search(),
                    self.graph_create(),
                    self.graph_link(),
                    self.graph_neighbors(),
                ]
            )
        if "communication" in svc:
            tools.extend([self.send_message(), self.list_messages()])

        super().__init__(*tools, name="khive")

    def _make_client(self):
        from khive import AsyncKhive

        return AsyncKhive(
            api_key=self._api_key,
            base_url=self._base_url,
            namespace=self._namespace,
        )

    # -- Memory ---------------------------------------------------------------

    def memory_recall(self):
        make_client = self._make_client

        @tool(
            name="memory_recall",
            description=(
                "Search persistent memory for relevant past findings, decisions, or context. "
                "Call BEFORE researching to avoid duplicate work."
            ),
        )
        async def _recall(
            query: Annotated[str, Field(description="Natural language search query.")],
            limit: Annotated[int, Field(description="Max results.", ge=1, le=20)] = 5,
        ) -> ToolResult:
            async with make_client() as client:
                result = await client.memory.recall(query=query, limit=limit)
                items = result.items if hasattr(result, "items") else result
                return ToolResult(str(items))

        return _recall

    def memory_remember(self):
        make_client = self._make_client

        @tool(
            name="memory_remember",
            description=(
                "Save a finding or decision to persistent memory. "
                "Be specific: numbers, citations, concrete claims."
            ),
        )
        async def _remember(
            content: Annotated[str, Field(description="What to remember.")],
            importance: Annotated[float, Field(ge=0, le=1)] = 0.7,
        ) -> ToolResult:
            async with make_client() as client:
                await client.memory.remember(content=content, importance=importance)
                return ToolResult(f"Remembered: {content}")

        return _remember

    # -- Graph ----------------------------------------------------------------

    def graph_search(self):
        make_client = self._make_client

        @tool(
            name="graph_search",
            description=("Search knowledge graph for related papers, datasets, concepts."),
        )
        async def _search(
            query: Annotated[str, Field(description="Search terms.")],
        ) -> ToolResult:
            async with make_client() as client:
                result = await client.graph.search(query=query)
                return ToolResult(str(result if isinstance(result, list) else [result]))

        return _search

    def graph_create(self):
        make_client = self._make_client

        @tool(name="graph_add_entity", description="Create an entity in the knowledge graph.")
        async def _create(
            entity_type: Annotated[
                str, Field(description="Type: person, paper, dataset, concept.")
            ],
            name: Annotated[str, Field(description="Display name.")],
        ) -> ToolResult:
            async with make_client() as client:
                result = await client.graph.create(type=entity_type, name=name)
                return ToolResult(str(result))

        return _create

    def graph_link(self):
        make_client = self._make_client

        @tool(name="graph_add_link", description="Link two entities in the knowledge graph.")
        async def _link(
            source: Annotated[str, Field(description="Source entity.")],
            target: Annotated[str, Field(description="Target entity.")],
            relation: Annotated[str, Field(description="Relation: cites, contradicts, extends.")],
        ) -> ToolResult:
            async with make_client() as client:
                result = await client.graph.link(source=source, target=target, relation=relation)
                return ToolResult(str(result))

        return _link

    def graph_neighbors(self):
        make_client = self._make_client

        @tool(name="graph_neighbors", description="Get entities connected to a given entity.")
        async def _neighbors(
            entity_id: Annotated[str, Field(description="Entity ID.")],
        ) -> ToolResult:
            async with make_client() as client:
                result = await client.graph.neighbors(id=entity_id)
                return ToolResult(str(result if isinstance(result, list) else [result]))

        return _neighbors

    # -- Communication --------------------------------------------------------

    def send_message(self):
        make_client = self._make_client

        @tool(name="send_message", description="Send a message to another agent or team.")
        async def _send(
            content: Annotated[str, Field(description="Message body.")],
            to: Annotated[str, Field(description="Recipient team or agent.")],
            subject: Annotated[str, Field(description="Subject line.")] = "",
        ) -> ToolResult:
            async with make_client() as client:
                await client.communication.send(content=content, to=to)
                return ToolResult(f"Sent to {to}")

        return _send

    def list_messages(self):
        make_client = self._make_client

        @tool(name="list_messages", description="Check inbox for messages from other teams.")
        async def _list(
            limit: Annotated[int, Field(ge=1, le=50)] = 5,
        ) -> ToolResult:
            async with make_client() as client:
                result = await client.communication.list(limit=limit)
                return ToolResult(str(result if isinstance(result, list) else [result]))

        return _list
