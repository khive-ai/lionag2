"""Assembly policies with tool call/result pairing integrity.

AG2's SlidingWindowPolicy only strips leading orphan ToolResultsEvents.
This module provides SafeSlidingWindowPolicy which ensures pairing across
the entire assembled context — no orphaned tool results at any position.
"""

from autogen.beta.context import ConversationContext as Context
from autogen.beta.events import BaseEvent, ToolResultsEvent
from autogen.beta.events.tool_events import ToolCallsEvent


def ensure_tool_pairing(events: list[BaseEvent]) -> list[BaseEvent]:
    """Drop orphaned tool results whose ToolCallsEvent is missing.

    Filters at the individual result level — a ToolResultsEvent with
    mixed valid/orphan results keeps only the valid ones.
    """
    call_ids: set[str] = set()
    for e in events:
        if isinstance(e, ToolCallsEvent):
            for c in e.calls:
                cid = getattr(c, "id", None)
                if cid:
                    call_ids.add(cid)

    out: list[BaseEvent] = []
    for e in events:
        if not isinstance(e, ToolResultsEvent):
            out.append(e)
            continue
        paired = [r for r in e.results if getattr(r, "parent_id", None) in call_ids]
        if paired:
            if len(paired) == len(e.results):
                out.append(e)
            else:
                out.append(ToolResultsEvent(results=paired))
    return out


class SafeSlidingWindowPolicy:
    """SlidingWindowPolicy + full tool call/result pairing.

    Drop-in replacement for AG2's SlidingWindowPolicy.
    """

    name = "safe_sliding_window"

    def __init__(self, max_events: int, transparent: bool = False) -> None:
        self._max = max_events
        self._transparent = transparent

    async def apply(
        self,
        prompts: list[str],
        events: list[BaseEvent],
        context: Context,
    ) -> tuple[list[str], list[BaseEvent]]:
        total = len(events)
        if total <= self._max:
            return prompts, events
        trimmed = ensure_tool_pairing(events[-self._max :])
        if self._transparent:
            prompts = prompts + [f"[{self.name}] Showing last {len(trimmed)} of {total} events."]
        return prompts, trimmed
