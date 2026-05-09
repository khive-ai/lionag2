"""Thread-safe, async-safe, ID-keyed ordered collection for AG2 events.

Ported from lionagi's Pile — adapted for AG2's BaseEvent which stores
fields in __dict__ via setattr. IDs are stamped onto events on include.

Polymorphic __getitem__:
    pile[uuid]              → single event by ID
    pile[0]                 → by index in progression
    pile[-3:]               → slice
    pile[FindingEmitted]    → all events of type
    pile[TypeA | TypeB]     → union type filter
    pile[lambda e: ...]     → predicate filter
    pile[ag2_condition]     → AG2 Condition filter
    pile[progression]       → events in that progression's order
"""

from __future__ import annotations

import types as _types
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TypeVar, overload, get_args
from uuid import UUID

from autogen.beta.events.conditions import Condition

from .progression import Progression
from .utils import IDUtils as iu, SyncUtils as su

T = TypeVar("T")


class Pile:

    __slots__ = ("_items", "_prog", "_type_index", "_lock", "_alock")

    def __init__(self) -> None:
        self._items: dict[UUID, Any] = {}
        self._prog = Progression()
        self._type_index: dict[str, list[UUID]] = {}
        self._lock = su.lock()
        self._alock = su.alock()

    # -- Mutations (sync, locked) ---------------------------------------------

    @su._sync
    def include(self, items: Any | list[Any], /) -> list[UUID]:
        """Add items. Stamps UUID on each. Returns list of IDs."""
        if not isinstance(items, list):
            items = [items]
        if any(iu.is_id(item) for item in items):
            raise ValueError("Pass objects, not raw IDs")
        result = []
        for item in items:
            uid = iu.ensure_id(item)
            if uid not in self._items:
                self._items[uid] = item
                self._prog.append(uid)
                tname = iu.type_name(item)
                self._type_index.setdefault(tname, []).append(uid)
            result.append(uid)
        return result

    @su._sync
    def exclude(self, items: Any | list[Any], /) -> list[Any]:
        """Remove items by object or ID. Returns removed items."""
        if not isinstance(items, list):
            items = [items]
        removed = []
        for item in items:
            uid = iu.get_id(item, surpress=True)
            if uid is None:
                continue
            event = self._items.pop(uid, None)
            if event is not None:
                self._prog.remove(uid)
                tname = iu.type_name(event)
                ids = self._type_index.get(tname, [])
                if uid in ids:
                    ids.remove(uid)
                removed.append(event)
        return removed

    @su._sync
    def evict(self, predicate: Callable[[Any], bool]) -> list[Any]:
        """Remove all matching predicate."""
        to_remove = [uid for uid, ev in self._items.items() if predicate(ev)]
        return self._remove_uids(to_remove)

    @su._sync
    def evict_before(self, index: int) -> list[Any]:
        """Remove events before index (keep tail)."""
        if index <= 0:
            return []
        uids = self._prog[:index]
        return self._remove_uids(uids)

    @su._sync
    def clear(self) -> None:
        self._items.clear()
        self._prog.clear()
        self._type_index.clear()

    @su._sync
    def replace(self, events: Iterable[Any]) -> None:
        """Replace all contents (compaction)."""
        self._items.clear()
        self._prog.clear()
        self._type_index.clear()
        for ev in events:
            uid = iu.ensure_id(ev)
            self._items[uid] = ev
            self._prog.append(uid)
            tname = iu.type_name(ev)
            self._type_index.setdefault(tname, []).append(uid)

    # -- Async mutations ------------------------------------------------------

    @su._async
    async def ainclude(self, items: Any | list[Any], /) -> list[UUID]:
        if not isinstance(items, list):
            items = [items]
        result = []
        for item in items:
            uid = iu.ensure_id(item)
            if uid not in self._items:
                self._items[uid] = item
                self._prog.append(uid)
                tname = iu.type_name(item)
                self._type_index.setdefault(tname, []).append(uid)
            result.append(uid)
        return result

    @su._async
    async def aexclude(self, items: Any | list[Any], /) -> list[Any]:
        if not isinstance(items, list):
            items = [items]
        removed = []
        for item in items:
            uid = iu.get_id(item, surpress=True)
            if uid is None:
                continue
            event = self._items.pop(uid, None)
            if event is not None:
                self._prog.remove(uid)
                tname = iu.type_name(event)
                ids = self._type_index.get(tname, [])
                if uid in ids:
                    ids.remove(uid)
                removed.append(event)
        return removed

    @su._async
    async def aevict(self, predicate: Callable[[Any], bool]) -> list[Any]:
        to_remove = [uid for uid, ev in self._items.items() if predicate(ev)]
        return self._remove_uids(to_remove)

    # -- Reads ----------------------------------------------------------------

    def get(self, uid: UUID | str) -> Any | None:
        uid = iu.get_id(uid, surpress=True)
        return self._items.get(uid) if uid else None

    def by_type(self, *event_types: type) -> list[Any]:
        """All events of given type(s), in insertion order."""
        result = []
        for et in event_types:
            tname = iu.type_name_from_class(et)
            for uid in self._type_index.get(tname, []):
                if uid in self._items:
                    result.append(self._items[uid])
        return result

    def __getitem__(self, key: Any) -> Any:
        """Polymorphic access.

        pile[uuid]           → single event
        pile[0], pile[-3:]   → by index/slice
        pile[SomeType]       → list of that type
        pile[TypeA | TypeB]  → union type filter
        pile[lambda e: ...]  → predicate filter
        pile[condition]      → AG2 Condition filter
        pile[progression]    → events in progression order
        """
        # UUID lookup
        if isinstance(key, UUID):
            return self._items[key]

        # String → try UUID
        if isinstance(key, str):
            uid = iu.get_id(key, surpress=True)
            if uid and uid in self._items:
                return self._items[uid]
            raise KeyError(f"Event {key!r} not found")

        # Index / slice
        if isinstance(key, int):
            uid = self._prog[key]
            return self._items[uid]
        if isinstance(key, slice):
            uids = self._prog[key]
            return [self._items[uid] for uid in uids if uid in self._items]

        # Progression
        if isinstance(key, Progression):
            return [self._items[uid] for uid in key if uid in self._items]

        # AG2 Condition DSL (TypeCondition, OpCondition, AndCondition, etc.)
        # Check before type/callable — Condition is ABC with __call__,
        # and event classes are also Conditions via _ConditionMeta.
        if isinstance(key, Condition):
            return [ev for ev in self if key(ev)]

        # Type union (TypeA | TypeB) — Python 3.10+ types.UnionType
        if isinstance(key, _types.UnionType):
            member_types = get_args(key)
            return [ev for ev in self if isinstance(ev, member_types)]

        # Single type — also a Condition via _ConditionMeta, but caught
        # above. This branch handles plain types that aren't AG2 events.
        if isinstance(key, type):
            return self.by_type(key)

        # Callable / lambda predicate
        if callable(key):
            return [ev for ev in self if key(ev)]

        raise TypeError(f"Unsupported key type: {type(key).__name__}")

    def __contains__(self, item: UUID | str | Any) -> bool:
        if isinstance(item, UUID):
            return item in self._items
        uid = iu.get_id(item, surpress=True)
        return uid is not None and uid in self._items

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __iter__(self) -> Iterator[Any]:
        for uid in list(self._prog):
            if uid in self._items:
                yield self._items[uid]

    def __reversed__(self) -> Iterator[Any]:
        for uid in reversed(self._prog):
            if uid in self._items:
                yield self._items[uid]

    @property
    def ids(self) -> list[UUID]:
        return list(self._prog)

    @property
    def type_counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self._type_index.items()}

    def values(self) -> list[Any]:
        return list(self)

    def items(self) -> list[tuple[UUID, Any]]:
        return [(uid, self._items[uid]) for uid in self._prog if uid in self._items]

    def tail(self, n: int) -> list[Any]:
        return self[-n:]

    def head(self, n: int) -> list[Any]:
        return self[:n]

    def __repr__(self) -> str:
        types = ", ".join(
            f"{k.rsplit('.', 1)[-1]}:{v}" for k, v in self.type_counts.items()
        )
        return f"Pile(len={len(self)}, types={{{types}}})"

    # -- Private --------------------------------------------------------------

    def _remove_uids(self, uids: list[UUID]) -> list[Any]:
        removed = []
        for uid in uids:
            event = self._items.pop(uid, None)
            if event is not None:
                removed.append(event)
                tname = iu.type_name(event)
                ids = self._type_index.get(tname, [])
                if uid in ids:
                    ids.remove(uid)
        self._prog.remove_many(set(uids))
        return removed


# ---------------------------------------------------------------------------
# AG2 Storage protocol adapter
# ---------------------------------------------------------------------------


class PileStorage:
    """AG2 Storage backed by Pile.

    Drop-in for MemoryStorage::

        stream = MemoryStream(storage=PileStorage())
        # events get UUID .id stamped on save
        # pile = stream.history.storage.pile_for(stream.id)
    """

    def __init__(self) -> None:
        self._piles: dict[Any, Pile] = {}

    def _get(self, stream_id: Any) -> Pile:
        if stream_id not in self._piles:
            self._piles[stream_id] = Pile()
        return self._piles[stream_id]

    @property
    def pile(self) -> Pile | None:
        piles = list(self._piles.values())
        return piles[0] if len(piles) == 1 else None

    def pile_for(self, stream_id: Any) -> Pile:
        return self._get(stream_id)

    async def save_event(self, event: Any, context: Any) -> None:
        pile = self._get(context.stream.id)
        await pile.ainclude(event)

    async def get_history(self, stream_id: Any) -> Iterable[Any]:
        return self._get(stream_id).values()

    async def set_history(self, stream_id: Any, events: Iterable[Any]) -> None:
        self._get(stream_id).replace(list(events))

    async def drop_history(self, stream_id: Any) -> None:
        self._get(stream_id).clear()
