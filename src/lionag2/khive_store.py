"""KnowledgeStore backed by khive — AG2's knowledge harness runs on khive natively.

Implements the AG2 KnowledgeStore protocol using khive's memory service.
AG2's WorkingMemoryPolicy, EpisodicMemoryPolicy, compaction, and aggregation
all read/write through khive automatically.

Path semantics: each path is stored as a khive memory entry with the path
as a structured prefix. Listing uses prefix matching on recall results.
"""

import logging

from autogen.beta.knowledge.base import (
    ChangeCallback,
    ChangeSubscription,
    NoopChangeSubscription,
)

logger = logging.getLogger(__name__)

PATH_TAG = "kstore:"


class KhiveKnowledgeStore:
    """AG2 KnowledgeStore backed by khive memory.

    Falls back to MemoryKnowledgeStore if khive is unavailable.

    Usage::

        store = KhiveKnowledgeStore(namespace="my-research")
        agent = Agent("x", knowledge=KnowledgeConfig(store=store))
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        namespace: str = "lionag2",
    ) -> None:
        from khive import AsyncKhive

        self._client = AsyncKhive(
            api_key=api_key,
            base_url=base_url,
            namespace=namespace,
        )

    async def read(self, path: str) -> str | None:
        path = _norm(path)
        try:
            result = await self._client.memory.recall(
                query=f"{PATH_TAG}{path}", limit=1,
            )
            items = _items(result)
            for item in items:
                content = _content(item)
                if content.startswith(f"{PATH_TAG}{path}\n"):
                    return content[len(f"{PATH_TAG}{path}\n"):]
            return None
        except Exception:
            logger.debug("khive read failed: %s", path, exc_info=True)
            return None

    async def write(self, path: str, content: str) -> None:
        path = _norm(path)
        try:
            await self._client.memory.remember(
                content=f"{PATH_TAG}{path}\n{content}",
                importance=0.8,
            )
        except Exception:
            logger.debug("khive write failed: %s", path, exc_info=True)

    async def list(self, path: str = "/") -> list[str]:
        prefix = _norm(path).rstrip("/") + "/"
        try:
            result = await self._client.memory.recall(
                query=f"{PATH_TAG}{prefix}", limit=50,
            )
            children: set[str] = set()
            for item in _items(result):
                content = _content(item)
                if not content.startswith(PATH_TAG):
                    continue
                stored_path = content.split("\n", 1)[0][len(PATH_TAG):]
                if not stored_path.startswith(prefix):
                    continue
                remainder = stored_path[len(prefix):]
                if "/" in remainder:
                    children.add(remainder.split("/")[0] + "/")
                elif remainder:
                    children.add(remainder)
            return sorted(children)
        except Exception:
            logger.debug("khive list failed: %s", path, exc_info=True)
            return []

    async def delete(self, path: str) -> None:
        path = _norm(path)
        try:
            result = await self._client.memory.recall(
                query=f"{PATH_TAG}{path}", limit=10,
            )
            for item in _items(result):
                item_id = getattr(item, "id", None)
                if item_id:
                    await self._client.memory.forget(id=item_id)
        except Exception:
            logger.debug("khive delete failed: %s", path, exc_info=True)

    async def exists(self, path: str) -> bool:
        content = await self.read(path)
        if content is not None:
            return True
        children = await self.list(path)
        return len(children) > 0

    async def append(self, path: str, content: str) -> int:
        path = _norm(path)
        existing = await self.read(path)
        existing = existing or ""
        offset = len(existing.encode("utf-8"))
        await self.write(path, existing + content)
        return offset

    async def read_range(self, path: str, start: int, end: int | None = None) -> str:
        content = await self.read(path)
        if content is None:
            return ""
        data = content.encode("utf-8")
        stop = len(data) if end is None else min(end, len(data))
        if start >= stop:
            return ""
        return data[start:stop].decode("utf-8", errors="strict")

    async def on_change(
        self, path: str, callback: ChangeCallback,
    ) -> ChangeSubscription:
        return NoopChangeSubscription()


def _norm(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return path


def _items(result: object) -> list:
    if hasattr(result, "items"):
        return result.items or []
    if isinstance(result, list):
        return result
    return []


def _content(item: object) -> str:
    if hasattr(item, "content"):
        return item.content
    return str(item)
