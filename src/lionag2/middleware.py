"""Tool middleware for cleaning oversized search results.

Exa and other search tools sometimes return raw HTML or massive
content. This middleware cleans and truncates tool results before
they hit the stream, preserving useful text while respecting
context budgets.
"""

import re

from autogen.beta import Context, ToolResult
from autogen.beta.events import TextInput, ToolCallEvent
from autogen.beta.events.tool_events import ToolResultEvent

MAX_RESULT_CHARS = 20_000


async def clean_search_results(call_next, event: ToolCallEvent, ctx: Context):
    """Middleware that cleans HTML and truncates oversized tool results.

    Applied to search/fetch tools. Returns the ToolResultEvent with
    cleaned text parts.
    """
    result_event = await call_next(event, ctx)

    if not isinstance(result_event, ToolResultEvent):
        return result_event

    tool_result = result_event.result
    cleaned_parts = []
    for part in tool_result.parts:
        if isinstance(part, TextInput):
            text = _clean_html(part.content)
            if len(text) > MAX_RESULT_CHARS:
                text = text[:MAX_RESULT_CHARS] + "\n[truncated]"
            cleaned_parts.append(TextInput(text))
        else:
            cleaned_parts.append(part)

    result_event.result = ToolResult(*cleaned_parts)
    return result_event


def _clean_html(text: str) -> str:
    """Strip HTML artifacts from search results."""
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
