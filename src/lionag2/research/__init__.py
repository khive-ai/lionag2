"""lionag2.research — recursive multi-agent research pipeline."""

from .engine import ResearchEngine, research
from .models import CrossCheckReport, ExplorationResult, PaperDraft, QualityMetrics

__all__ = [
    "ResearchEngine",
    "research",
    "ExplorationResult",
    "PaperDraft",
    "QualityMetrics",
    "CrossCheckReport",
]
