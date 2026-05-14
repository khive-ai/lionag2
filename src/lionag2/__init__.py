"""lionag2 — reactive recursive research on AG2 beta.

Core primitives (Pile, Progression, Flow) in lionag2.core.
Generic engine in lionag2.engine.
Research pipeline in lionag2.research.
"""

__version__ = "0.3.0"

from .core import Flow, Pile, Progression
from .engine import Engine
from .research import ResearchEngine, research
from .research.models import ExplorationResult, PaperDraft

__all__ = [
    "Engine",
    "Flow",
    "Pile",
    "Progression",
    "ResearchEngine",
    "ExplorationResult",
    "PaperDraft",
    "research",
    "__version__",
]
