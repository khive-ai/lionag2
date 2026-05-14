"""Structured output models for code review."""

from typing import Literal

from pydantic import BaseModel, Field


class ReviewIssue(BaseModel):
    file: str = ""
    line: int = 0
    severity: Literal["critical", "high", "medium", "low", "info"] = "medium"
    category: str = ""
    title: str
    description: str
    suggestion: str = ""


class ReviewReport(BaseModel):
    summary: str
    verdict: Literal["approve", "request_changes", "comment"] = "comment"
    issues: list[ReviewIssue] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    praise: list[str] = Field(default_factory=list)
    risk_level: Literal["none", "low", "medium", "high", "critical"] = "low"
