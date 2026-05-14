"""Emission tools for the code review pipeline.

Agents use these to emit typed events that the engine records.
"""

from autogen.beta import Context, tool

from ..engine import HandoffRequested
from .events import IssueFound, QuestionRaised


@tool
async def emit_issue(
    ctx: Context,
    title: str,
    description: str,
    severity: str = "medium",
    category: str = "",
    file: str = "",
    line: int = 0,
    suggestion: str = "",
) -> str:
    """Flag a code issue. severity: critical/high/medium/low/info. category: security/logic/performance/style/maintainability."""
    agent = str(ctx.variables.get("agent_name", "unknown"))
    await ctx.send(
        IssueFound(
            file=file,
            line=line,
            severity=severity,
            category=category,
            title=title,
            description=description,
            suggestion=suggestion,
            source_agent=agent,
        )
    )
    return f"Issue flagged: [{severity}] {title}"


@tool
async def emit_question(
    ctx: Context,
    question: str,
    context: str = "",
) -> str:
    """Flag something that needs human clarification before a verdict."""
    agent = str(ctx.variables.get("agent_name", "unknown"))
    await ctx.send(
        QuestionRaised(question=question, context=context, source_agent=agent)
    )
    return f"Question raised: {question}"


@tool
async def handoff(ctx: Context, next_agent: str, reason: str = "") -> str:
    """Hand off to the next specialist. Pass 'done' to end the review."""
    await ctx.send(HandoffRequested(next_agent=next_agent, reason=reason))
    return f"Handing off to {next_agent}" if next_agent != "done" else "Review complete."


REVIEW_TOOLS = [emit_issue, emit_question, handoff]
