"""Stream manager — named streams, context carry-over, event bus.

Streams are progressions. An agent's view of the world is what's on
its stream. Context management = stream manipulation.

The bus is a MemoryStream used for reactive coordination. Team streams
forward matched events to the bus via bridge subscribers.
"""

import logging

from autogen.beta import MemoryStream
from autogen.beta.context import ConversationContext
from autogen.beta.events import BaseEvent

from .events import (
    ContradictionFound,
    DepthRequested,
    FindingEmitted,
    PaperGapEvent,
    PivotDetected,
)

logger = logging.getLogger(__name__)

BRIDGE_EVENT_TYPES = (
    FindingEmitted,
    DepthRequested,
    ContradictionFound,
    PivotDetected,
    PaperGapEvent,
)


def _make_bus_context(bus: MemoryStream) -> ConversationContext:
    """Minimal context for bus.send() calls."""
    return ConversationContext(stream=bus)


class StreamManager:
    """Manages named streams and context transfer between them."""

    def __init__(self) -> None:
        self.bus = MemoryStream()
        self._bus_ctx = _make_bus_context(self.bus)
        self._streams: dict[str, MemoryStream] = {}

    def get_or_create(self, name: str) -> MemoryStream:
        if name not in self._streams:
            stream = MemoryStream()
            self._install_bridge(stream)
            self._streams[name] = stream
        return self._streams[name]

    def _install_bridge(self, stream: MemoryStream) -> None:
        """Subscribe a bridge that forwards research events to the bus.

        This is how specialist ctx.send() events reach the bus watches.
        """
        bus = self.bus
        bus_ctx = self._bus_ctx

        async def _forward(event: BaseEvent, ctx: ConversationContext) -> None:
            if isinstance(event, BRIDGE_EVENT_TYPES):
                await bus.send(event, bus_ctx)

        stream.subscribe(_forward)

    @property
    def all_streams(self) -> dict[str, MemoryStream]:
        return dict(self._streams)

    async def carry_for_depth(
        self,
        parent_stream: str | MemoryStream,
        child_stream: str | MemoryStream,
        depth: int,
    ) -> int:
        """Carry context from parent to child stream, depth-aware."""
        src = self._resolve(parent_stream)
        dst = self._resolve(child_stream)
        dst_ctx = ConversationContext(stream=dst)
        all_events = list(await src.history.get_events())

        if depth >= 2:
            high = [
                e
                for e in all_events
                if isinstance(e, FindingEmitted) and e.novelty > 0.6
            ]
            for e in high[-5:]:
                await dst.history.storage.save_event(e, dst_ctx)
            return len(high[-5:])

        relevant = [
            e for e in all_events if isinstance(e, FindingEmitted)
        ][-15:]
        for e in relevant:
            await dst.history.storage.save_event(e, dst_ctx)
        return len(relevant)

    async def emit_to_bus(self, event: BaseEvent) -> None:
        """Emit a coordination event to the shared bus."""
        await self.bus.send(event, self._bus_ctx)

    async def collect_all_findings(self) -> list[FindingEmitted]:
        """Gather FindingEmitted events from all streams + bus."""
        all_findings: list[FindingEmitted] = []
        for stream in self._streams.values():
            events = list(await stream.history.get_events())
            all_findings.extend(
                e for e in events if isinstance(e, FindingEmitted)
            )
        bus_events = list(await self.bus.history.get_events())
        all_findings.extend(
            e for e in bus_events if isinstance(e, FindingEmitted)
        )
        return all_findings

    def _resolve(self, stream: str | MemoryStream) -> MemoryStream:
        if isinstance(stream, str):
            return self.get_or_create(stream)
        return stream
