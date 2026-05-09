"""lionag2 — reactive recursive research on AG2 beta.

Core primitives (Pile, Progression, Flow) in lionag2.core.
Research pipeline in lionag2.research.
"""

__version__ = "0.3.0"

from .core import Flow, Pile, Progression
from .research import ResearchEngine, research
from .research.models import ExplorationResult, PaperDraft, QualityMetrics

__all__ = [
    "Flow",
    "Pile",
    "Progression",
    "ResearchEngine",
    "ExplorationResult",
    "PaperDraft",
    "QualityMetrics",
    "research",
    "__version__",
]
