"""Flow — shared items pile + named streams backed by progressions.

    flow.items                       → Pile (all events across all streams)
    flow.items[FindingEmitted]       → type filter
    flow.items[condition]            → AG2 Condition DSL
    flow.streams["surveyor"]         → MemoryStream (pass to agent.ask)
    flow.streams["bus"]              → MemoryStream (coordination bus)

All streams share one Pile. Each stream's FlowStorage writes to the same
items pile and appends to its own progression. Same event object in
multiple progressions = object vs reference.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from .pile import Pile
from .progression import Progression
from .utils import IDUtils as iu


class FlowStorage:
    """AG2 Storage protocol backed by a shared Flow + named progression.

    get_history runs ensure_tool_pairing to strip orphaned ToolResultsEvents
    that lost their parent ToolCallsEvent — prevents OpenAI 400 errors.
    """

    __slots__ = ("_flow", "_name")

    def __init__(self, flow: Flow, name: str) -> None:
        self._flow = flow
        self._name = name

    async def save_event(self, event: Any, context: Any) -> None:
        self._flow.include(event, progressions=[self._name])

    async def get_history(self, stream_id: Any) -> Iterable[Any]:
        from .policies import ensure_tool_pairing
        events = self._flow.progression_items(self._name)
        return ensure_tool_pairing(events)

    async def set_history(self, stream_id: Any, events: Iterable[Any]) -> None:
        self._flow.replace_progression(self._name, list(events))

    async def drop_history(self, stream_id: Any) -> None:
        self._flow.clear_progression(self._name)


class _StreamRegistry:
    """Dict-like access to named MemoryStreams backed by Flow.

    Streams auto-create on access. Each stream = MemoryStream + FlowStorage
    pointing to the same Flow items pile with its own progression.
    """

    __slots__ = ("_flow", "_streams")

    def __init__(self, flow: Flow) -> None:
        self._flow = flow
        self._streams: dict[str, Any] = {}

    def __getitem__(self, name: str) -> Any:
        if name not in self._streams:
            self._create(name)
        return self._streams[name]

    def __contains__(self, name: str) -> bool:
        return name in self._streams

    def __iter__(self):
        return iter(self._streams)

    def __len__(self) -> int:
        return len(self._streams)

    def keys(self):
        return self._streams.keys()

    def values(self):
        return self._streams.values()

    def items(self):
        return self._streams.items()

    def _create(self, name: str, condition=None) -> Any:
        from autogen.beta import MemoryStream

        storage = FlowStorage(self._flow, name)
        stream = MemoryStream(storage=storage)
        self._streams[name] = stream

        if condition is not None:
            self._flow._register_condition(name, condition)

        return stream

    def _register(self, name: str, stream: Any) -> None:
        self._streams[name] = stream


class Flow:
    """Shared items pile + named streams.

    Usage::

        flow = Flow()

        # Streams auto-create on access
        await agent.ask("...", stream=flow.streams["surveyor"])

        # All events, all streams
        flow.items[FindingEmitted]
        flow.items[FindingEmitted.novelty > 0.7]

        # Events in one progression's order
        flow["bus"]  # shortcut for flow.progression_items("bus")
    """

    __slots__ = ("_items", "_progressions", "_conditions", "_streams", "_lock", "name")

    def __init__(self, name: str | None = None) -> None:
        self._items = Pile()
        self._progressions: dict[str, Progression] = {}
        self._conditions: dict[str, Any] = {}  # name → Condition/callable for auto-routing
        self._lock = threading.RLock()
        self.name = name
        self._streams = _StreamRegistry(self)

    @property
    def items(self) -> Pile:
        return self._items

    @property
    def streams(self) -> _StreamRegistry:
        return self._streams

    # -- Stream creation -------------------------------------------------------

    def new_stream(self, condition=None, name: str | None = None) -> Any:
        """Create a new stream, optionally filtered by condition.

        If condition given, existing matching items are backfilled and
        future includes auto-route to this stream's progression.

        Args:
            condition: AG2 Condition, type, or callable. Events matching
                       this are auto-appended to the progression.
            name: Stream name. Auto-generated if None.

        Returns:
            MemoryStream — passable to agent.ask(stream=...).

        Examples::

            # All high-novelty findings
            s = flow.new_stream(FindingEmitted.novelty > 0.7, name="high_novelty")

            # All contradictions
            s = flow.new_stream(ContradictionFound, name="contradictions")

            # Plain stream (manual population)
            s = flow.new_stream(name="my_team")
        """
        from uuid import uuid4

        if name is None:
            name = f"stream_{uuid4().hex[:8]}"

        with self._lock:
            self._ensure_progression(name)

            if condition is not None:
                # Normalize: type → isinstance check
                if isinstance(condition, type):
                    _cond = condition
                    condition = lambda e, _c=_cond: isinstance(e, _c)
                self._conditions[name] = condition

                # Backfill existing items that match
                prog = self._progressions[name]
                for uid, item in self._items.items():
                    if condition(item):
                        prog.include(uid)

            return self._streams._create(name, condition)

    def _register_condition(self, name: str, condition) -> None:
        """Register a condition for auto-routing (called by _StreamRegistry)."""
        self._conditions[name] = condition

    # -- Progression management -----------------------------------------------

    def _ensure_progression(self, name: str) -> Progression:
        if name not in self._progressions:
            self._progressions[name] = Progression(name=name)
        return self._progressions[name]

    def progression_items(self, name: str) -> list[Any]:
        """Items in a named progression's order."""
        prog = self._progressions.get(name)
        if prog is None:
            return []
        return [self._items.get(uid) for uid in prog if self._items.get(uid) is not None]

    def replace_progression(self, name: str, events: list[Any]) -> None:
        """Replace a progression's contents (compaction)."""
        with self._lock:
            prog = self._ensure_progression(name)
            prog.clear()
            for ev in events:
                uid = iu.ensure_id(ev)
                if uid not in self._items:
                    self._items.include(ev)
                prog.include(uid)

    def clear_progression(self, name: str) -> None:
        """Clear a progression (items stay in pile)."""
        with self._lock:
            prog = self._progressions.get(name)
            if prog:
                prog.clear()

    @property
    def progression_names(self) -> list[str]:
        return list(self._progressions.keys())

    # -- Item management ------------------------------------------------------

    def include(
        self,
        items: Any | list[Any],
        progressions: str | list[str] | None = None,
    ) -> list[UUID]:
        """Add items to pile, append to named progressions, and auto-route.

        Auto-routing: for every condition-based progression, if the item
        matches the condition, its UUID is appended to that progression.
        """
        with self._lock:
            if not isinstance(items, list):
                items = [items]
            uids = self._items.include(items)

            # Explicit progressions
            if progressions:
                if isinstance(progressions, str):
                    progressions = [progressions]
                for pname in progressions:
                    prog = self._ensure_progression(pname)
                    for uid in uids:
                        prog.include(uid)

            # Auto-route to condition-based progressions
            if self._conditions:
                for uid, item in zip(uids, items):
                    for cname, cond in self._conditions.items():
                        try:
                            if cond(item):
                                self._ensure_progression(cname).include(uid)
                        except Exception:
                            pass

            return uids

    def exclude(self, items: Any | list[Any]) -> list[Any]:
        """Remove items from pile and all progressions."""
        with self._lock:
            if not isinstance(items, list):
                items = [items]
            uids = set()
            for item in items:
                uid = iu.get_id(item, surpress=True)
                if uid:
                    uids.add(uid)
            for prog in self._progressions.values():
                prog.remove_many(uids)
            return self._items.exclude(items)

    def evict(
        self,
        predicate,
        progressions: str | list[str] | None = None,
    ) -> list[Any]:
        """Evict events matching predicate.

        If progressions specified: remove references from those progressions
        only, items stay in pile.
        If None: remove from pile + all progressions.
        """
        with self._lock:
            if progressions is None:
                removed = self._items.evict(predicate)
                removed_ids = {iu.get_id(ev, surpress=True) for ev in removed}
                removed_ids.discard(None)
                for prog in self._progressions.values():
                    prog.remove_many(removed_ids)
                return removed

            if isinstance(progressions, str):
                progressions = [progressions]
            evicted = []
            for pname in progressions:
                prog = self._progressions.get(pname)
                if not prog:
                    continue
                to_remove = []
                for uid in list(prog):
                    item = self._items.get(uid)
                    if item is not None and predicate(item):
                        to_remove.append(uid)
                        evicted.append(item)
                prog.remove_many(set(to_remove))
            return evicted

    # -- Reads ----------------------------------------------------------------

    def __getitem__(self, name: str) -> list[Any]:
        """Shortcut: flow["bus"] = flow.progression_items("bus")."""
        return self.progression_items(name)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, item: Any) -> bool:
        return item in self._items

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._progressions.clear()

    def to_dict(self) -> dict[str, Any]:
        """Serialize entire flow — items + progressions. Polymorphic."""
        from autogen.beta.events._serialization import serialize_value
        return {
            "name": self.name,
            "items": [serialize_value(ev) for ev in self._items],
            "progressions": {
                name: [str(uid) for uid in prog]
                for name, prog in self._progressions.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Flow":
        """Reconstruct flow from serialized dict. Polymorphic event types."""
        from autogen.beta.events._serialization import deserialize_value
        flow = cls(name=data.get("name"))
        events = [deserialize_value(d) for d in data.get("items", [])]
        flow.include(events)
        for pname, uids in data.get("progressions", {}).items():
            flow._ensure_progression(pname)
            prog = flow._progressions[pname]
            for uid_str in uids:
                from uuid import UUID
                prog.include(UUID(uid_str))
        return flow

    def __repr__(self) -> str:
        progs = ", ".join(
            f"{name}:{len(p)}" for name, p in self._progressions.items()
        )
        return f"Flow(items={len(self._items)}, progressions=[{progs}])"
