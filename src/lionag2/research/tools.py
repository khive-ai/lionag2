"""Lightweight event-emission tools for typed handoff.

These are the ONLY custom tools in lionag2 — everything else
(search, fetch, code, memory, graph) comes from AG2 native
toolkits. These emit typed events that observers capture live.
"""

from autogen.beta import Context, tool

from .events import (
    ContradictionFound,
    DepthRequested,
    FindingEmitted,
    HandoffRequested,
    PaperGapEvent,
    PivotDetected,
)


@tool
async def emit_finding(
    ctx: Context,
    claim: str,
    evidence: str = "",
    novelty: float = 0.5,
    confidence: float = 0.5,
) -> str:
    """Emit a typed finding when you discover a source-backed claim."""
    agent = str(ctx.variables.get("agent_name", "unknown"))
    depth = int(ctx.variables.get("depth", 0))
    node_id = str(ctx.variables.get("node_id", ""))
    await ctx.send(
        FindingEmitted(
            claim=claim,
            evidence=evidence,
            source_agent=agent,
            node_id=node_id,
            novelty=novelty,
            confidence=confidence,
            depth=depth,
        )
    )
    return f"Finding emitted: {claim}"


@tool
async def request_depth(
    ctx: Context,
    question: str,
    novelty: float = 0.7,
) -> str:
    """Request a child research node for a high-value follow-up."""
    node_id = str(ctx.variables.get("node_id", ""))
    depth = int(ctx.variables.get("depth", 0))
    await ctx.send(
        DepthRequested(
            question=question,
            novelty=novelty,
            parent_node_id=node_id,
            parent_depth=depth,
        )
    )
    return f"Depth requested: {question}"


@tool
async def emit_contradiction(
    ctx: Context,
    claim_a: str,
    claim_b: str,
    source_a: str = "",
    source_b: str = "",
    severity: float = 0.5,
) -> str:
    """Flag conflicting claims across branches."""
    await ctx.send(
        ContradictionFound(
            claim_a=claim_a,
            claim_b=claim_b,
            source_a=source_a,
            source_b=source_b,
            severity=severity,
        )
    )
    return "Contradiction flagged"


@tool
async def emit_pivot(
    ctx: Context,
    description: str,
) -> str:
    """Flag that evidence contradicted the initial hypothesis."""
    agent = str(ctx.variables.get("agent_name", "unknown"))
    await ctx.send(PivotDetected(description=description, source_agent=agent))
    return "Pivot recorded"


@tool
async def emit_paper_gap(
    ctx: Context,
    section: str,
    description: str,
    research_question: str,
    priority: str = "medium",
) -> str:
    """Flag a gap in the paper that needs more research.

    research_question must be concrete and searchable, e.g.
    "What are RAFT vs Paxos latency benchmarks at 10K nodes?"
    NOT "More research needed on consensus."
    """
    await ctx.send(
        PaperGapEvent(
            section=section,
            description=description,
            research_question=research_question,
            priority=priority,
        )
    )
    return f"Gap flagged: [{priority}] {section}"


@tool
async def handoff(ctx: Context, next_agent: str, reason: str = "") -> str:
    """Hand off to another specialist when you've contributed what you can.

    Pass 'done' as next_agent to end the team discussion.
    Available specialists are listed in your system prompt.
    """
    await ctx.send(HandoffRequested(next_agent=next_agent, reason=reason))
    return f"Handing off to {next_agent}" if next_agent != "done" else "Team discussion complete."


EMISSION_TOOLS = [emit_finding, request_depth, emit_contradiction, emit_pivot, handoff]
PAPER_TOOLS = [emit_paper_gap]
