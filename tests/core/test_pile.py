import threading
from uuid import UUID, uuid4

import pytest
from autogen.beta.events import BaseEvent

from lionag2.core import Pile, Progression


class SimpleEvent(BaseEvent):
    text: str = ""
    score: float = 0.0


class OtherEvent(BaseEvent):
    value: int = 0


class TestPileBasic:
    def test_empty(self):
        p = Pile()
        assert len(p) == 0
        assert not p
        assert list(p) == []

    def test_include_single(self):
        p = Pile()
        e = SimpleEvent(text="hello")
        uids = p.include(e)
        assert len(uids) == 1
        assert len(p) == 1
        assert p

    def test_include_list(self):
        p = Pile()
        events = [SimpleEvent(text=f"e{i}") for i in range(3)]
        uids = p.include(events)
        assert len(uids) == 3
        assert len(p) == 3

    def test_include_stamps_lion_id(self):
        p = Pile()
        e = SimpleEvent(text="test")
        uids = p.include(e)
        assert isinstance(e.lion_id, UUID)
        assert e.lion_id == uids[0]

    def test_include_idempotent(self):
        p = Pile()
        e = SimpleEvent(text="test")
        p.include(e)
        p.include(e)
        assert len(p) == 1

    def test_include_rejects_raw_ids(self):
        p = Pile()
        with pytest.raises(ValueError, match="Pass objects"):
            p.include(uuid4())

    def test_exclude(self):
        p = Pile()
        e = SimpleEvent(text="test")
        p.include(e)
        removed = p.exclude(e)
        assert len(removed) == 1
        assert len(p) == 0

    def test_exclude_by_uuid(self):
        p = Pile()
        e = SimpleEvent(text="test")
        uids = p.include(e)
        removed = p.exclude(uids[0])
        assert len(removed) == 1

    def test_clear(self):
        p = Pile()
        p.include([SimpleEvent() for _ in range(5)])
        p.clear()
        assert len(p) == 0


class TestPileGet:
    def test_get_by_uuid(self):
        p = Pile()
        e = SimpleEvent(text="hello")
        uids = p.include(e)
        assert p.get(uids[0]) is e

    def test_get_missing(self):
        p = Pile()
        assert p.get(uuid4()) is None

    def test_get_by_string(self):
        p = Pile()
        e = SimpleEvent(text="hello")
        uids = p.include(e)
        assert p.get(str(uids[0])) is e


class TestPileGetitem:
    def test_by_uuid(self):
        p = Pile()
        e = SimpleEvent(text="hello")
        uids = p.include(e)
        assert p[uids[0]] is e

    def test_by_index(self):
        p = Pile()
        events = [SimpleEvent(text=f"e{i}") for i in range(3)]
        p.include(events)
        assert p[0] is events[0]
        assert p[-1] is events[2]

    def test_by_slice(self):
        p = Pile()
        events = [SimpleEvent(text=f"e{i}") for i in range(5)]
        p.include(events)
        result = p[1:3]
        assert len(result) == 2
        assert result[0] is events[1]

    def test_by_type(self):
        p = Pile()
        s1 = SimpleEvent(text="a")
        s2 = SimpleEvent(text="b")
        o1 = OtherEvent(value=1)
        p.include([s1, o1, s2])
        result = p[SimpleEvent]
        assert len(result) == 2
        assert s1 in result and s2 in result

    def test_by_callable(self):
        p = Pile()
        events = [SimpleEvent(text=f"e{i}", score=i * 0.1) for i in range(10)]
        p.include(events)
        result = p[lambda e: e.score > 0.5]
        assert all(e.score > 0.5 for e in result)
        assert len(result) == 4

    def test_by_progression(self):
        p = Pile()
        events = [SimpleEvent(text=f"e{i}") for i in range(5)]
        uids = p.include(events)
        prog = Progression(order=[uids[0], uids[4]])
        result = p[prog]
        assert len(result) == 2
        assert result[0] is events[0]
        assert result[1] is events[4]

    def test_unsupported_key(self):
        p = Pile()
        with pytest.raises(TypeError):
            p[3.14]


class TestPileByType:
    def test_single_type(self):
        p = Pile()
        p.include([SimpleEvent(text="a"), OtherEvent(value=1), SimpleEvent(text="b")])
        assert len(p.by_type(SimpleEvent)) == 2
        assert len(p.by_type(OtherEvent)) == 1

    def test_multiple_types(self):
        p = Pile()
        p.include([SimpleEvent(text="a"), OtherEvent(value=1)])
        result = p.by_type(SimpleEvent, OtherEvent)
        assert len(result) == 2

    def test_empty_result(self):
        p = Pile()
        p.include(SimpleEvent(text="a"))
        assert p.by_type(OtherEvent) == []


class TestPileContains:
    def test_by_uuid(self):
        p = Pile()
        e = SimpleEvent()
        uids = p.include(e)
        assert uids[0] in p

    def test_by_object(self):
        p = Pile()
        e = SimpleEvent()
        p.include(e)
        assert e in p

    def test_missing(self):
        p = Pile()
        assert uuid4() not in p


class TestPileIter:
    def test_insertion_order(self):
        p = Pile()
        events = [SimpleEvent(text=f"e{i}") for i in range(5)]
        p.include(events)
        assert list(p) == events

    def test_items(self):
        p = Pile()
        e = SimpleEvent(text="hello")
        uids = p.include(e)
        pairs = p.items()
        assert len(pairs) == 1
        assert pairs[0] == (uids[0], e)


class TestPileThreadSafety:
    def test_concurrent_include(self):
        p = Pile()
        errors = []

        def worker(batch_id):
            try:
                events = [SimpleEvent(text=f"b{batch_id}_e{i}") for i in range(50)]
                p.include(events)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(p) == 200
