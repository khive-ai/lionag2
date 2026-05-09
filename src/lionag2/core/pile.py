"""Thread-safe, ID-keyed ordered collection for AG2 events.

Polymorphic __getitem__:
    pile[uuid]              → single event by ID
    pile[0]                 → by index in progression
    pile[-3:]               → slice
    pile[FindingEmitted]    → all events of type
    pile[TypeA | TypeB]     → union type filter
    pile[lambda e: ...]     → predicate filter
    pile[ag2_condition]     → AG2 Condition filter
"""

from __future__ import annotations

import types as _types
from collections.abc import Iterator
from typing import Any, TypeVar, get_args
from uuid import UUID

from autogen.beta.events.conditions import Condition

from .progression import Progression
from .utils import IDUtils as iu
from .utils import SyncUtils as su

T = TypeVar("T")


class Pile:
    __slots__ = ("_items", "_prog", "_type_index", "_lock")

    def __init__(self) -> None:
        self._items: dict[UUID, Any] = {}
        self._prog = Progression()
        self._type_index: dict[str, list[UUID]] = {}
        self._lock = su.lock()

    # -- Mutations ------------------------------------------------------------

    @su._sync
    def include(self, items: Any | list[Any], /) -> list[UUID]:
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
        if not isinstance(items, list):
            items = [items]
        removed = []
        for item in items:
            uid = iu.get_id(item, suppress=True)
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
    def clear(self) -> None:
        self._items.clear()
        self._prog.clear()
        self._type_index.clear()

    # -- Reads ----------------------------------------------------------------

    def get(self, uid: UUID | str) -> Any | None:
        uid = iu.get_id(uid, suppress=True)
        return self._items.get(uid) if uid else None

    def by_type(self, *event_types: type) -> list[Any]:
        result = []
        for et in event_types:
            tname = iu.type_name_from_class(et)
            for uid in self._type_index.get(tname, []):
                if uid in self._items:
                    result.append(self._items[uid])
        return result

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, UUID):
            return self._items[key]

        if isinstance(key, str):
            uid = iu.get_id(key, suppress=True)
            if uid and uid in self._items:
                return self._items[uid]
            raise KeyError(f"Event {key!r} not found")

        if isinstance(key, int):
            uid = self._prog[key]
            return self._items[uid]
        if isinstance(key, slice):
            uids = self._prog[key]
            return [self._items[uid] for uid in uids if uid in self._items]

        if isinstance(key, Progression):
            return [self._items[uid] for uid in key if uid in self._items]

        if isinstance(key, Condition):
            return [ev for ev in self if key(ev)]

        if isinstance(key, _types.UnionType):
            member_types = get_args(key)
            return [ev for ev in self if isinstance(ev, member_types)]

        if isinstance(key, type):
            return self.by_type(key)

        if callable(key):
            return [ev for ev in self if key(ev)]

        raise TypeError(f"Unsupported key type: {type(key).__name__}")

    def __contains__(self, item: UUID | str | Any) -> bool:
        if isinstance(item, UUID):
            return item in self._items
        uid = iu.get_id(item, suppress=True)
        return uid is not None and uid in self._items

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __iter__(self) -> Iterator[Any]:
        for uid in list(self._prog):
            if uid in self._items:
                yield self._items[uid]

    def items(self) -> list[tuple[UUID, Any]]:
        return [(uid, self._items[uid]) for uid in self._prog if uid in self._items]

    def __repr__(self) -> str:
        types = ", ".join(
            f"{k.rsplit('.', 1)[-1]}:{v}"
            for k, v in ((k, len(v)) for k, v in self._type_index.items())
        )
        return f"Pile(len={len(self)}, types={{{types}}})"
