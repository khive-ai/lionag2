"""Typed events for the code review pipeline."""

from autogen.beta.events import BaseEvent, Field


class IssueFound(BaseEvent):
    """A code issue discovered by a specialist."""

    file: str = ""
    line: int = 0
    severity: str = Field(default="medium")
    category: str = ""
    title: str = ""
    description: str = ""
    suggestion: str = ""
    source_agent: str = "unknown"


class QuestionRaised(BaseEvent):
    """Something the reviewer needs human clarification on."""

    __transient__ = True
    question: str
    context: str = ""
    source_agent: str = "unknown"
