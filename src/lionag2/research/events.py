"""Typed events — all live in the Flow pile.

Two categories:
  Research events — emitted by specialists via ctx.send() tools.
  Engine events — emitted by the engine for coordination/observability.

All are BaseEvent subclasses with auto-stamped UUIDs.
"""

from autogen.beta.events import BaseEvent, Field


# ---------------------------------------------------------------------------
# Research events (specialist → bus via bridge)
# ---------------------------------------------------------------------------


class FindingEmitted(BaseEvent):
    claim: str
    evidence: str = ""
    source_agent: str = "unknown"
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
# Engine coordination events (engine → pile for observability)
# ---------------------------------------------------------------------------


class NodeRegistered(BaseEvent):
    """A research node was created."""
    node_id: str
    topic: str
    depth: int = 0
    parent_node_id: str = ""
    stream_name: str = ""


class TeamStarted(BaseEvent):
    node_id: str
    agents: list = Field(default_factory=list)
    depth: int = 0


class AgentTurnStarted(BaseEvent):
    __transient__ = True
    node_id: str
    agent: str


class AgentTurnDone(BaseEvent):
    node_id: str
    agent: str
    chars: int = 0


class AgentTurnError(BaseEvent):
    node_id: str
    agent: str
    error: str = ""


class UrlCaptured(BaseEvent):
    __transient__ = True
    title: str
    url: str


class TopicSeen(BaseEvent):
    """Normalized topic registered for dedup."""
    normalized: str
    node_id: str = ""


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
