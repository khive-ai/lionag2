"""lionag2.research — recursive multi-agent research pipeline."""

from .engine import ResearchEngine, research
from .models import CrossCheckReport, ExplorationResult, PaperDraft

__all__ = [
    "ResearchEngine",
    "research",
    "ExplorationResult",
    "PaperDraft",
    "CrossCheckReport",
]
