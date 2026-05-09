"""Typed research events for observer-based handoff.

Specialists emit these via context.send() during tool execution.
The engine registers observers on each coordinator.ask() call to
capture them in real time — findings get stored, depth requests
get queued, contradictions get flagged. The recursive BFS loop
is still the driver; observers augment it with live reactivity.
"""

from autogen.beta.events import BaseEvent, Field


class FindingEmitted(BaseEvent):
    """A specialist discovered a source-backed or code-backed claim."""

    claim: str
    evidence: str = ""
    source_agent: str = "unknown"
    novelty: float = Field(default=0.5)
    confidence: float = Field(default=0.5)
    depth: int = 0


class DepthRequested(BaseEvent):
    """A specialist wants a child node for a follow-up question."""

    question: str
    novelty: float = Field(default=0.7)
    parent_node_id: str = ""
    parent_depth: int = 0


class ContradictionFound(BaseEvent):
    """A specialist found conflicting claims across branches."""

    claim_a: str
    claim_b: str
    source_a: str = ""
    source_b: str = ""
    severity: float = Field(default=0.5)


class PivotDetected(BaseEvent):
    """Evidence contradicted the initial hypothesis."""

    description: str
    source_agent: str = "unknown"


class PaperGapEvent(BaseEvent):
    """Paper writer identified a gap that needs more research."""

    section: str
    description: str
    research_question: str
    priority: str = "medium"
