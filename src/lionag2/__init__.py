"""lionag2 — reactive recursive research on AG2 beta."""

__version__ = "0.2.0"

from .engine import ResearchEngine, research
from .models import ExplorationResult, PaperDraft, QualityMetrics

__all__ = [
    "ResearchEngine",
    "ExplorationResult",
    "PaperDraft",
    "QualityMetrics",
    "research",
    "__version__",
]
