import pytest
from autogen.beta.events import BaseEvent

from lionag2.core import Flow
from lionag2.core.flow import FlowStorage


class Alpha(BaseEvent):
    text: str = ""
    score: float = 0.0


class Beta(BaseEvent):
    value: int = 0


class TestFlowBasic:
    def test_empty(self):
        f = Flow("test")
        assert len(f) == 0
        assert f.name == "test"

    def test_include(self):
        f = Flow()
        uids = f.include(Alpha(text="hello"))
        assert len(f) == 1
        assert len(uids) == 1

    def test_include_list(self):
        f = Flow()
        events = [Alpha(text=f"e{i}") for i in range(3)]
        uids = f.include(events)
        assert len(f) == 3
        assert len(uids) == 3

    def test_include_to_progression(self):
        f = Flow()
        e = Alpha(text="hello")
        f.include(e, progressions=["bus"])
        items = f["bus"]
        assert len(items) == 1
        assert items[0] is e

    def test_include_to_multiple_progressions(self):
        f = Flow()
        e = Alpha(text="hello")
        f.include(e, progressions=["bus", "archive"])
        assert len(f["bus"]) == 1
        assert len(f["archive"]) == 1
        assert f["bus"][0] is f["archive"][0]

    def test_items_type_filter(self):
        f = Flow()
        f.include([Alpha(text="a"), Beta(value=1), Alpha(text="b")])
        assert len(f.items[Alpha]) == 2
        assert len(f.items[Beta]) == 1


class TestFlowStreams:
    def test_auto_create(self):
        f = Flow()
        stream = f.streams["bus"]
        assert stream is not None
        assert "bus" in f.streams

    def test_same_stream_returned(self):
        f = Flow()
        s1 = f.streams["bus"]
        s2 = f.streams["bus"]
        assert s1 is s2


class TestFlowConditionStreams:
    def test_new_stream_with_type_condition(self):
        f = Flow()
        f.new_stream(Alpha, name="alphas")
        f.include([Alpha(text="a"), Beta(value=1), Alpha(text="b")])
        items = f["alphas"]
        assert len(items) == 2
        assert all(isinstance(e, Alpha) for e in items)

    def test_new_stream_backfills(self):
        f = Flow()
        f.include([Alpha(text="a"), Alpha(text="b")])
        f.new_stream(Alpha, name="alphas")
        assert len(f["alphas"]) == 2

    def test_new_stream_with_callable(self):
        f = Flow()
        f.new_stream(lambda e: isinstance(e, Alpha) and e.score > 0.5, name="high")
        f.include([Alpha(score=0.3), Alpha(score=0.8), Alpha(score=0.9)])
        assert len(f["high"]) == 2

    def test_auto_name(self):
        f = Flow()
        stream = f.new_stream(Alpha)
        assert stream is not None


class TestFlowProgression:
    def test_progression_items_empty(self):
        f = Flow()
        assert f.progression_items("nonexistent") == []

    def test_progression_items_ordered(self):
        f = Flow()
        e1, e2, e3 = Alpha(text="1"), Alpha(text="2"), Alpha(text="3")
        f.include(e1, progressions=["queue"])
        f.include(e2, progressions=["queue"])
        f.include(e3, progressions=["queue"])
        items = f["queue"]
        assert items == [e1, e2, e3]

    def test_clear_progression(self):
        f = Flow()
        f.include(Alpha(text="a"), progressions=["bus"])
        f.clear_progression("bus")
        assert f["bus"] == []
        assert len(f) == 1

    def test_replace_progression(self):
        f = Flow()
        e1 = Alpha(text="old")
        f.include(e1, progressions=["bus"])
        e2 = Alpha(text="new")
        f.replace_progression("bus", [e2])
        items = f["bus"]
        assert len(items) == 1
        assert items[0].text == "new"


class TestFlowSerialization:
    def test_round_trip(self):
        f = Flow("myflow")
        f.include([Alpha(text="a", score=0.5), Beta(value=42)], progressions=["main"])
        f.include(Alpha(text="b"), progressions=["side"])

        data = f.to_dict()
        f2 = Flow.from_dict(data)

        assert f2.name == "myflow"
        assert len(f2) == 3
        assert len(f2.items[Alpha]) == 2
        assert len(f2.items[Beta]) == 1

    def test_empty_round_trip(self):
        f = Flow("empty")
        data = f.to_dict()
        f2 = Flow.from_dict(data)
        assert f2.name == "empty"
        assert len(f2) == 0


class TestFlowStorageProtocol:
    @pytest.mark.asyncio
    async def test_save_and_get(self):

        f = Flow()
        storage = FlowStorage(f, "test_stream")
        e = Alpha(text="hello")
        await storage.save_event(e, context=None)
        assert len(f) == 1
        history = list(await storage.get_history("any"))
        assert len(history) == 1

    @pytest.mark.asyncio
    async def test_drop_history(self):

        f = Flow()
        storage = FlowStorage(f, "test_stream")
        await storage.save_event(Alpha(text="a"), context=None)
        await storage.save_event(Alpha(text="b"), context=None)
        await storage.drop_history("any")
        history = list(await storage.get_history("any"))
        assert len(history) == 0
        assert len(f) == 2


class TestFlowGetitem:
    def test_getitem_shortcut(self):
        f = Flow()
        f.include(Alpha(text="a"), progressions=["bus"])
        assert f["bus"] == f.progression_items("bus")

    def test_repr(self):
        f = Flow("test")
        f.include(Alpha(), progressions=["bus"])
        r = repr(f)
        assert "bus:1" in r
