import pytest
from autogen.beta.events import BaseEvent
from autogen.beta.events.tool_events import (
    ToolCallEvent,
    ToolCallsEvent,
    ToolResult,
    ToolResultEvent,
    ToolResultsEvent,
)

from lionag2.core.policies import SafeSlidingWindowPolicy, ensure_tool_pairing


def _make_call(call_id: str) -> ToolCallsEvent:
    return ToolCallsEvent(calls=[ToolCallEvent(id=call_id, name="fn", arguments="{}")])


def _make_result(parent_id: str) -> ToolResultsEvent:
    return ToolResultsEvent(
        results=[ToolResultEvent(parent_id=parent_id, name="fn", result=ToolResult("ok"))]
    )


class SimpleEvent(BaseEvent):
    text: str = ""


class TestEnsureToolPairing:
    def test_no_tool_events(self):
        events = [SimpleEvent(text="a"), SimpleEvent(text="b")]
        assert ensure_tool_pairing(events) == events

    def test_paired_kept(self):
        events = [_make_call("c1"), _make_result("c1")]
        result = ensure_tool_pairing(events)
        assert len(result) == 2

    def test_orphan_dropped(self):
        events = [_make_result("orphan"), SimpleEvent(text="a")]
        result = ensure_tool_pairing(events)
        assert len(result) == 1
        assert isinstance(result[0], SimpleEvent)

    def test_mid_window_orphan(self):
        events = [
            _make_call("c1"),
            _make_result("c1"),
            _make_result("missing"),
            SimpleEvent(text="a"),
        ]
        result = ensure_tool_pairing(events)
        assert len(result) == 3
        assert not any(
            isinstance(e, ToolResultsEvent)
            and any(r.parent_id == "missing" for r in e.results)
            for e in result
        )


    def test_mixed_valid_and_orphan_results(self):
        valid = ToolResultEvent(parent_id="c1", name="fn", result=ToolResult("ok"))
        orphan = ToolResultEvent(parent_id="missing", name="fn", result=ToolResult("bad"))
        mixed = ToolResultsEvent(results=[valid, orphan])
        events = [_make_call("c1"), mixed]
        result = ensure_tool_pairing(events)
        assert len(result) == 2
        filtered = result[1]
        assert isinstance(filtered, ToolResultsEvent)
        assert len(filtered.results) == 1
        assert filtered.results[0].parent_id == "c1"

    def test_empty_calls(self):
        events = [_make_result("orphan")]
        result = ensure_tool_pairing(events)
        assert len(result) == 0


class TestSafeSlidingWindowPolicy:
    @pytest.mark.asyncio
    async def test_under_limit(self):
        policy = SafeSlidingWindowPolicy(max_events=10)
        events = [SimpleEvent(text=f"e{i}") for i in range(5)]
        prompts, result = await policy.apply([], events, context=None)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_over_limit_trims(self):
        policy = SafeSlidingWindowPolicy(max_events=3)
        events = [SimpleEvent(text=f"e{i}") for i in range(10)]
        prompts, result = await policy.apply([], events, context=None)
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_transparent_adds_prompt(self):
        policy = SafeSlidingWindowPolicy(max_events=3, transparent=True)
        events = [SimpleEvent(text=f"e{i}") for i in range(10)]
        prompts, result = await policy.apply(["sys"], events, context=None)
        assert len(prompts) == 2
        assert "last" in prompts[1].lower()
