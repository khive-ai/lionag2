"""NB09 — Cross-Check & Paper Loop (no API keys needed, shows data models)."""
from lionag2.research.models import Contradiction, CrossCheckReport, PaperDraft, PaperGap

# CrossCheckReport structure
report = CrossCheckReport(
    contradictions=[
        Contradiction(
            claim_a="AFM glue dominates across all dopings",
            claim_b="Phonon contribution significant at overdoping",
            source_a="theorist d=0",
            source_b="analyst d=1",
            resolution_hint="Restrict AFM claim to optimal doping",
        )
    ],
    gaps=[
        PaperGap(
            section="findings",
            description="No data on underdoped regime",
            research_question="How does pairing symmetry change below optimal doping?",
            priority="high",
        )
    ],
    redundancies=["Multiple branches surveyed the same HgBaCaCuO data"],
    summary="One contradiction found between depth-0 and depth-1 claims.",
)

print(f"=== CrossCheckReport ===")
print(f"Contradictions: {len(report.contradictions)}")
print(f"Gaps: {len(report.gaps)}")
print(f"Summary: {report.summary}")

# PaperDraft structure
paper = PaperDraft(
    title="Spin-Fluctuation Pairing in Cuprate Superconductors",
    abstract="We investigate the pairing mechanism in layered cuprates...",
    body_markdown="## 1. Introduction\n\nHigh-Tc superconductivity...",
    limitations=["Limited to hole-doped cuprates", "No electron-doped data"],
    gaps=[
        PaperGap(
            section="findings",
            description="Missing underdoped regime data",
            research_question="How does gap symmetry evolve below optimal doping?",
            priority="high",
        ),
    ],
    quality_score=0.65,
)

print(f"\n=== PaperDraft ===")
print(f"Quality: {paper.quality_score}")
print(f"High-priority gaps: {len([g for g in paper.gaps if g.priority == 'high'])}")
print(f"Rendered length: {len(paper.as_markdown())} chars")
print(paper.as_markdown()[:300])
