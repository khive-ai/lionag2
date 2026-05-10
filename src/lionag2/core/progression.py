"""Ordered sequence of UUIDs with O(1) membership."""

from collections import deque
from collections.abc import Iterator
from typing import overload
from uuid import UUID


class Progression:
    __slots__ = ("_order", "_members", "name")

    def __init__(self, order: list[UUID] | None = None, name: str | None = None) -> None:
        self._order: deque[UUID] = deque(order or [])
        self._members: set[UUID] = set(self._order)
        self.name = name

    def append(self, uid: UUID) -> None:
        self._order.append(uid)
        self._members.add(uid)

    def include(self, uid: UUID) -> bool:
        if uid in self._members:
            return False
        self._order.append(uid)
        self._members.add(uid)
        return True

    def remove(self, uid: UUID) -> bool:
        if uid not in self._members:
            return False
        self._order = deque(x for x in self._order if x != uid)
        self._members.discard(uid)
        return True

    def remove_many(self, uids: set[UUID]) -> int:
        before = len(self._order)
        self._order = deque(x for x in self._order if x not in uids)
        self._members -= uids
        return before - len(self._order)

    def clear(self) -> None:
        self._order.clear()
        self._members.clear()

    @overload
    def __getitem__(self, key: int) -> UUID: ...
    @overload
    def __getitem__(self, key: slice) -> list[UUID]: ...

    def __getitem__(self, key: int | slice) -> UUID | list[UUID]:
        if isinstance(key, slice):
            return list(self._order)[key]
        return self._order[key]

    def __contains__(self, uid: UUID) -> bool:
        return uid in self._members

    def __len__(self) -> int:
        return len(self._order)

    def __iter__(self) -> Iterator[UUID]:
        return iter(self._order)

    def __repr__(self) -> str:
        return f"Progression(name={self.name!r}, len={len(self)})"
