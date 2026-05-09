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

from collections.abc import Iterable
from typing import Any
from uuid import UUID, uuid4

from autogen.beta import MemoryStream
from autogen.beta.events._serialization import deserialize_value, serialize_value

from .pile import Pile
from .progression import Progression
from .utils import IDUtils as iu
from .utils import SyncUtils as su


class FlowStorage:
    """AG2 Storage protocol backed by a shared Flow + named progression.

    get_history runs ensure_tool_pairing to strip orphaned ToolResultsEvents.
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


class Flow:
    __slots__ = (
        "_items",
        "_progressions",
        "_conditions",
        "_streams",
        "_lock",
        "name",
    )

    def __init__(self, name: str | None = None) -> None:
        self._items = Pile()
        self._progressions: dict[str, Progression] = {}
        self._conditions: dict[str, Any] = {}
        self._streams: dict[str, MemoryStream] = {}
        self._lock = su.lock()
        self.name = name

    @property
    def items(self) -> Pile:
        return self._items

    @property
    def streams(self) -> _Streams:
        return _Streams(self)

    # -- Stream creation -------------------------------------------------------

    def _get_or_create_stream(self, name: str) -> MemoryStream:
        if name not in self._streams:
            self._ensure_progression(name)
            storage = FlowStorage(self, name)
            self._streams[name] = MemoryStream(storage=storage)
        return self._streams[name]

    def new_stream(self, condition=None, name: str | None = None) -> MemoryStream:
        if name is None:
            name = f"stream_{uuid4().hex[:8]}"

        with self._lock:
            self._ensure_progression(name)

            if condition is not None:
                if isinstance(condition, type):
                    _cond = condition
                    condition = lambda e, _c=_cond: isinstance(e, _c)
                self._conditions[name] = condition

                prog = self._progressions[name]
                for uid, item in self._items.items():
                    if condition(item):
                        prog.include(uid)

            storage = FlowStorage(self, name)
            stream = MemoryStream(storage=storage)
            self._streams[name] = stream
            return stream

    # -- Progression management -----------------------------------------------

    def _ensure_progression(self, name: str) -> Progression:
        if name not in self._progressions:
            self._progressions[name] = Progression(name=name)
        return self._progressions[name]

    def progression_items(self, name: str) -> list[Any]:
        prog = self._progressions.get(name)
        if prog is None:
            return []
        return [self._items.get(uid) for uid in prog if self._items.get(uid) is not None]

    @su._sync
    def replace_progression(self, name: str, events: list[Any]) -> None:
        prog = self._ensure_progression(name)
        prog.clear()
        for ev in events:
            uid = iu.ensure_id(ev)
            if uid not in self._items:
                self._items.include(ev)
            prog.include(uid)

    @su._sync
    def clear_progression(self, name: str) -> None:
        prog = self._progressions.get(name)
        if prog:
            prog.clear()

    # -- Item management ------------------------------------------------------
    @su._sync
    def include(
        self,
        items: Any | list[Any],
        progressions: str | list[str] | None = None,
    ) -> list[UUID]:
        if not isinstance(items, list):
            items = [items]
        uids = self._items.include(items)

        if progressions:
            if isinstance(progressions, str):
                progressions = [progressions]
            for pname in progressions:
                prog = self._ensure_progression(pname)
                for uid in uids:
                    prog.include(uid)

        if self._conditions:
            for uid, item in zip(uids, items):
                for cname, cond in self._conditions.items():
                    try:
                        if cond(item):
                            self._ensure_progression(cname).include(uid)
                    except Exception:
                        pass

        return uids

    # -- Reads ----------------------------------------------------------------

    def __getitem__(self, name: str) -> list[Any]:
        return self.progression_items(name)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        progs = ", ".join(f"{name}:{len(p)}" for name, p in self._progressions.items())
        return f"Flow(items={len(self._items)}, progressions=[{progs}])"

    # -- Serialization --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "items": [serialize_value(ev) for ev in self._items],
            "progressions": {
                name: [str(uid) for uid in prog] for name, prog in self._progressions.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Flow:
        flow = cls(name=data.get("name"))
        events = [deserialize_value(d) for d in data.get("items", [])]
        flow.include(events)
        for pname, uid_strs in data.get("progressions", {}).items():
            flow._ensure_progression(pname)
            prog = flow._progressions[pname]
            for uid_str in uid_strs:
                prog.include(UUID(uid_str))
        return flow


class _Streams:
    """Thin proxy — flow.streams["name"] auto-creates streams."""

    __slots__ = ("_flow",)

    def __init__(self, flow: Flow) -> None:
        self._flow = flow

    def __getitem__(self, name: str) -> MemoryStream:
        return self._flow._get_or_create_stream(name)

    def __contains__(self, name: str) -> bool:
        return name in self._flow._streams
