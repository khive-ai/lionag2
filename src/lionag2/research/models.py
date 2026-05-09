"""Typed research artifacts.

These models are the structured interface between research and synthesis.
Specialists produce them; the knowledge store accumulates them; the paper
writer consumes them. Gaps in coverage loop back as new research nodes.
"""

import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Research artifacts (produced by specialists)
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    title: str
    authors: str = ""
    year: str = ""
    url: str = ""
    relevance: str = ""


class Finding(BaseModel):
    claim: str
    evidence: str
    citations: list[Citation] = Field(default_factory=list)
    novelty: str = ""
    confidence: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description=(
            "0-1. Boost when: real citation, code verification, cross-branch "
            "corroboration. Penalize when: no source, weak evidence, contradicted."
        ),
    )
    code_ref: str | None = None
    source_agent: str = "unknown"
    depth: int = 0


class DatasetCard(BaseModel):
    name: str
    url: str = ""
    schema_desc: str = ""
    load_code: str = ""
    license: str = ""
    source_agent: str = "DataDigger"


class AnalysisResult(BaseModel):
    summary: str
    code: str = ""
    output: str = ""
    key_numbers: list[str] = Field(default_factory=list)
    supported: bool = True


class Alternative(BaseModel):
    hypothesis: str
    evidence: str = ""
    danger_level: Literal["low", "medium", "high"] = "low"


class Contradiction(BaseModel):
    claim_a: str
    claim_b: str
    source_a: str = ""
    source_b: str = ""
    resolution_hint: str = ""


class OpenQuestion(BaseModel):
    question: str
    novelty_score: float = Field(ge=0, le=1)
    reason: str = ""


class PaperPart(BaseModel):
    section: str = Field(description="abstract | introduction | findings | discussion | conclusion")
    content: str
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)


# ---------------------------------------------------------------------------
# Node-level output (what each exploration node produces)
# ---------------------------------------------------------------------------


class ExplorationResult(BaseModel):
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    pivot: str | None = Field(
        default=None,
        description="If evidence contradicts initial hypothesis, describe the pivot",
    )
    paper_parts: list[PaperPart] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Paper evaluation (quality gate that can loop back to research)
# ---------------------------------------------------------------------------


class PaperGap(BaseModel):
    section: str
    description: str
    research_question: str
    priority: Literal["high", "medium", "low"] = "medium"


class PaperDraft(BaseModel):
    title: str
    abstract: str
    body_markdown: str
    limitations: list[str] = Field(default_factory=list)
    gaps: list[PaperGap] = Field(default_factory=list)
    quality_score: float = Field(default=0.0, ge=0, le=1)

    def as_markdown(self) -> str:
        lim = "\n".join(f"- {x}" for x in self.limitations) or "- None stated."
        return (
            f"# {self.title}\n\n"
            f"## Abstract\n\n{self.abstract}\n\n"
            f"{self.body_markdown}\n\n"
            f"## Limitations\n\n{lim}\n"
        )


class CrossCheckReport(BaseModel):
    contradictions: list[Contradiction] = Field(default_factory=list)
    gaps: list[PaperGap] = Field(default_factory=list)
    redundancies: list[str] = Field(default_factory=list)
    summary: str = ""


class QualityMetrics(BaseModel):
    citation_count: int
    novelty_score: float = Field(ge=0, le=1)
    evidence_quality: float = Field(ge=0, le=1)
    contradiction_count: int = 0
    correction_count: int = 0
    coverage_score: float = Field(ge=0, le=1)
    paper_completeness: float = Field(ge=0, le=1)
    verdict: str


# ---------------------------------------------------------------------------
# Research tree
# ---------------------------------------------------------------------------


class NodeStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETE = "complete"
    FAILED = "failed"
    PRUNED = "pruned"


class ExplorationNode(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    topic: str
    depth: int = 0
    parent_id: str | None = None
    status: NodeStatus = NodeStatus.PENDING
    findings: list[Finding] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    result: ExplorationResult | None = None


class ExplorationTree(BaseModel):
    root_id: str
    nodes: dict[str, ExplorationNode] = Field(default_factory=dict)
    max_depth: int = 3
    max_concurrent: int = 4
    topic: str = ""
