"""Typed events — research domain.

Two categories:
  Research events — emitted by specialists via ctx.send() tools.
  Engine events — emitted by the engine for coordination/observability.

Engine-level events (TopicSeen, NodeRegistered, TeamStarted,
HandoffRequested, UrlCaptured) live in lionag2.engine and are
re-exported here for backward compatibility.
"""

from autogen.beta.events import BaseEvent, Field

from ..engine import (
    HandoffRequested,
    NodeRegistered,
    TeamStarted,
    TopicSeen,
    UrlCaptured,
)

# ---------------------------------------------------------------------------
# Research events (specialist → engine via agent observers)
# ---------------------------------------------------------------------------


class FindingEmitted(BaseEvent):
    claim: str
    evidence: str = ""
    source_agent: str = "unknown"
    node_id: str = ""
    novelty: float = Field(default=0.5)
    confidence: float = Field(default=0.5)
    depth: int = 0


class DepthRequested(BaseEvent):
    question: str
    novelty: float = Field(default=0.7)
    parent_node_id: str = ""
    parent_depth: int = 0


class ContradictionFound(BaseEvent):
    claim_a: str
    claim_b: str
    source_a: str = ""
    source_b: str = ""
    severity: float = Field(default=0.5)


class PivotDetected(BaseEvent):
    description: str
    source_agent: str = "unknown"


class PaperGapEvent(BaseEvent):
    section: str
    description: str
    research_question: str
    priority: str = "medium"


# ---------------------------------------------------------------------------
# Engine coordination events (re-exported from lionag2.engine)
# ---------------------------------------------------------------------------

# NodeRegistered, TeamStarted, HandoffRequested, UrlCaptured, TopicSeen
# imported above — available as research.events.X for backward compat


class CrossCheckDone(BaseEvent):
    contradictions: int = 0
    gaps: int = 0


class PaperDrafted(BaseEvent):
    iteration: int = 0
    quality: float = Field(default=0.0)
    gaps: int = 0


class ExplorationComplete(BaseEvent):
    total_nodes: int = 0
    total_findings: int = 0
    max_depth: int = 0
    paper_quality: float = Field(default=0.0)


__all__ = [
    "ContradictionFound",
    "CrossCheckDone",
    "DepthRequested",
    "ExplorationComplete",
    "FindingEmitted",
    "HandoffRequested",
    "NodeRegistered",
    "PaperDrafted",
    "PaperGapEvent",
    "PivotDetected",
    "TeamStarted",
    "TopicSeen",
    "UrlCaptured",
]
