"""Ordered sequence of UUIDs with O(1) membership.

Ported from lionagi — deque-based, not independently thread-safe.
Pile provides the synchronization.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator
from typing import overload
from uuid import UUID


class Progression:
    """Ordered deque of UUIDs with O(1) membership via set."""

    __slots__ = ("_order", "_members", "name")

    def __init__(self, order: Iterable[UUID] | None = None, name: str | None = None) -> None:
        self._order: deque[UUID] = deque(order or [])
        self._members: set[UUID] = set(self._order)
        self.name = name

    def append(self, uid: UUID) -> None:
        self._order.append(uid)
        self._members.add(uid)

    def extend(self, uids: Iterable[UUID]) -> None:
        for uid in uids:
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

    def pop(self, index: int = -1) -> UUID:
        if index == -1 or index == len(self._order) - 1:
            uid = self._order.pop()
        elif index == 0:
            uid = self._order.popleft()
        else:
            uid = self._order[index]
            del self._order[index]
        if uid not in self._order:
            self._members.discard(uid)
        return uid

    def popleft(self) -> UUID:
        uid = self._order.popleft()
        if uid not in self._order:
            self._members.discard(uid)
        return uid

    def insert(self, index: int, uid: UUID) -> None:
        self._order.insert(index, uid)
        self._members.add(uid)

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

    def __bool__(self) -> bool:
        return bool(self._order)

    def __iter__(self) -> Iterator[UUID]:
        return iter(self._order)

    def __reversed__(self) -> Iterator[UUID]:
        return reversed(self._order)

    def __repr__(self) -> str:
        return f"Progression(name={self.name!r}, len={len(self)})"
