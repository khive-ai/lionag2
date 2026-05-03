"""Recursive self-exploratory research engine.

Replaces the static plan→execute→synthesis pipeline with a recursive
exploration tree where agents discover things, run code, and spawn
sub-investigations dynamically.

Entry point: ``run_exploration(topic, queue, ...)``
"""

import asyncio
import logging
import os
import subprocess
import time
import uuid

import lionagi as li
from pydantic import BaseModel, Field

from .models import TeamResult  # noqa: F401 — re-exported for callers

logger = logging.getLogger(__name__)

__all__ = [
    "NodeStatus",
    "Finding",
    "OpenQuestion",
    "CodeBlock",
    "ExplorationNode",
    "ExplorationResult",
    "ExplorationTree",
    "QualityMetrics",
    "SharedKnowledge",
    "explore_node",
    "run_exploration",
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

EXPLORER_SYSTEM = """\
You are a research explorer conducting genuine scientific investigation.

You have access to tools:
- tavily_search(query): Search the web for academic papers, datasets, and research sources. USE THIS for every claim that needs evidence.

Your exploration MUST:
1. SEARCH FIRST using tavily_search — find real papers, datasets, citations before making claims
2. Identify 2-4 key findings with CITATIONS (title, authors, year, URL)
3. For each finding, assess NOVELTY — how does this compare to prior art?
4. Write Python code for quantitative verification: statistics, hypothesis tests, data analysis, algorithm pseudocode
5. Identify 1-3 genuinely novel follow-up questions
6. If your findings CONTRADICT prior findings from parent branches, flag as PIVOT and explain what changed
7. SELF-CORRECT: if search results contradict your initial reasoning, update your position — don't ignore the evidence

For novelty_score:
- 0.9+: completely unexpected, must investigate
- 0.7-0.9: interesting and non-obvious
- 0.5-0.7: predictable
- <0.5: already covered, skip

Code blocks: self-contained Python. Use only: math, statistics, collections, json, re, datetime.

For EVERY exploration, also produce paper_parts — draft sections for the final research paper.
Map your findings to paper sections: findings → "findings", contradictions → "discussion", context → "introduction"."""


CROSS_CHECK_SYSTEM = """\
You are a research reviewer performing cross-section analysis.

Given findings from multiple independent research branches, you must:
1. Identify CONTRADICTIONS between branches (branch A says X, branch B says Y)
2. Identify GAPS — important aspects no branch covered
3. Identify REDUNDANCIES — overlapping findings that should be merged
4. Suggest CORRECTIONS with evidence

Be specific. Quote the exact claims that contradict. Don't manufacture disagreements."""


PAPER_SYSTEM = """\
You are a scientific writer producing a substantial research paper (3000-5000 words, ~8-12 pages)
from multi-agent recursive exploration findings.

PAPER STRUCTURE (use exactly these markdown headings):

## Abstract — 200 words. State the research question, methodology (multi-agent recursive exploration), key findings (with numbers), and main conclusion.

## 1. Introduction
   - Restate the research question and why it matters
   - Cite at least 5 prior works to motivate the problem
   - State the paper's contribution
   - Roadmap of the paper

## 2. Background and Related Work — Cite 10+ sources here. Group by theme. Use ### subheadings for sub-themes.

## 3. Methodology
   - Describe the recursive multi-agent exploration: Surveyor → Analyst → Critic teams, branch spawning by novelty score, shared knowledge via memory + graph + cross-team messaging
   - Describe verification: code execution sandbox, cross-section correction, self-correction pass
   - Use ### subheadings: 3.1 Architecture, 3.2 Knowledge Sharing, 3.3 Verification Protocol

## 4. Findings — THIS IS THE LONGEST SECTION. Organize THEMATICALLY (not by branch). Use ### subheadings (4.1, 4.2, ...). For each finding:
   - State the claim precisely
   - Provide the supporting citation in [Author, Year] format
   - Include actual numerical data from code execution where available — use LaTeX math: $p < 0.05$, $r^2 = 0.83$, etc.
   - Note confidence level explicitly
   - When multiple sources agree, group them
   - When sources contradict, present both sides

## 5. Discussion
   - Synthesize the findings: what's the bigger picture?
   - Discuss pivots where evidence contradicted initial hypotheses
   - Unresolved contradictions and what would be needed to resolve them
   - Implications and applications

## 6. Limitations — what the multi-agent exploration could NOT verify or could only weakly support

## 7. Conclusion — 3-4 paragraphs. Restate the key contributions and outline future work.

## References — list all cited sources in numbered format: [1] Author. (Year). Title. Venue. URL.

REQUIREMENTS:
- Total length: 3000-5000 words minimum.
- Cite 30+ distinct sources across the paper.
- Use math notation where it helps: $E = mc^2$ inline, or display math:
  $$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$$
- Use markdown tables for quantitative results where applicable.
- When the agents ran code, include the actual output in code blocks: ```python ... ``` then ```output ... ```
- Be honest about contradictions; do not paper over them.
- Write in formal academic tone."""

# ---------------------------------------------------------------------------
# Enums and core data models
# ---------------------------------------------------------------------------

from enum import StrEnum  # noqa: E402 — after __all__


class NodeStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETE = "complete"
    PRUNED = "pruned"


# ---------------------------------------------------------------------------
# Agent roster — configurable roles with distinct tools and prompts
# ---------------------------------------------------------------------------


class AgentRole(BaseModel):
    name: str = Field(description="Agent name")
    role: str = Field(description="Role description")
    tools: list[str] = Field(description="Tool names this agent can use")
    system_prompt: str = Field(description="System prompt for this agent")


DEFAULT_AGENTS = [
    AgentRole(
        name="Surveyor",
        role="Literature scout — broad coverage of papers, surveys, prior art",
        tools=["tavily_search", "fetch_url", "memory_recall", "graph_search", "list_messages"],
        system_prompt=(
            "You are Surveyor. You are NOT writing a Wikipedia summary — you are doing real "
            "research. Your job is to surface a SUBSTANTIAL, OPINIONATED source list including "
            "alternative framings of the question.\n\n"
            "Depth-aware workflow:\n"
            "- depth=0 (root): broad coverage. Find the canonical papers, the most-cited surveys, "
            "  AND find at least 2 papers that DISAGREE with the consensus. The job is map territory.\n"
            "- depth=1: this is a sub-investigation of a specific sub-claim. Go DEEPER, not broader. "
            "  Find papers that drill into the mechanism, edge cases, or implementation details. "
            "  Skip generic surveys.\n"
            "- depth=2+: very narrow. Find specific empirical results, ablation studies, dataset cards, "
            "  reproductions, or failure-mode analyses.\n\n"
            "Tool workflow (MANDATORY in this order):\n"
            "1. list_messages() — see if other teams flagged anything you should incorporate.\n"
            "2. memory_recall('<topic>') — check what other branches already discovered. Do NOT duplicate.\n"
            "3. graph_search('<key concepts>') — see what entities are already in the shared graph.\n"
            "4. tavily_search() — issue 3-5 queries from DIFFERENT angles. Examples for one topic:\n"
            "   - 'X benchmark results 2024'\n"
            "   - 'X failure modes limitations'\n"
            "   - 'X alternative approach contrarian'\n"
            "   - 'X dataset reproducibility'\n"
            "   - 'critique of X'\n"
            "5. fetch_url(url) — for at least 3 of your top results, fetch the actual page so you "
            "   quote REAL text from the paper / dataset card / blog. Snippets alone are NOT enough.\n\n"
            "Output (8-12 sources minimum, one per line):\n"
            "  TITLE | AUTHORS | YEAR | URL | 2-3 sentence contribution from the ACTUAL READ "
            "  (specifics: what method, what dataset, what numerical results). Mark [snippet only] "
            "  if you didn't fetch the page.\n\n"
            "Also call out 1-2 ALTERNATIVE framings of the research question that the consensus "
            "literature ignores.\n\n"
            "End your turn with: 'SURVEY COMPLETE — DataDigger, find datasets.'"
        ),
    ),
    AgentRole(
        name="DataDigger",
        role="Dataset hunter — finds real datasets, characterizes them, attaches to claims",
        tools=["tavily_search", "fetch_url", "memory_recall", "graph_add_entity", "graph_add_link"],
        system_prompt=(
            "You are DataDigger. Real research needs real data. Your job is to hunt down "
            "specific datasets, benchmarks, or empirical artifacts that the next agent (Analyst) "
            "can actually load and analyze.\n\n"
            "Tool workflow:\n"
            "1. memory_recall('<topic> dataset') — what datasets have other branches already used?\n"
            "2. tavily_search() — issue at least 2 queries:\n"
            "   - '<topic> huggingface dataset'\n"
            "   - '<topic> kaggle' or '<topic> paperswithcode dataset'\n"
            "   - '<topic> benchmark' (TruthfulQA, MMLU, GSM8K, ARC for LLM topics, etc.)\n"
            "3. fetch_url(<dataset_card_url>) for the 2-3 most promising candidates. Read the "
            "   actual card: how many rows, what columns, what labels, what license, how to load.\n"
            "4. For each dataset you found, graph_add_entity(name=<dataset>, entity_type='dataset', "
            "   description='<size, schema, source, license, loading code>').\n"
            "5. graph_add_link(<dataset>, <paper>, 'used_in') for each paper that uses this dataset.\n\n"
            "Output: a CONCRETE list of 2-3 datasets with their loading instructions:\n"
            "  DATASET | URL | SIZE | SCHEMA | LICENSE | HOW TO LOAD (one line of code, e.g. "
            "  `from datasets import load_dataset; ds = load_dataset('truthful_qa','generation')`).\n\n"
            "If no usable dataset exists, say so explicitly — don't fabricate one. Suggest a "
            "synthetic-data plan instead.\n\n"
            "End your turn with: 'DATASETS COLLECTED — Theorist, formalize the mechanism.'"
        ),
    ),
    AgentRole(
        name="Theorist",
        role="Mechanism formalizer — extracts the underlying model / equations / assumptions",
        tools=["tavily_search", "fetch_url", "memory_recall", "memory_remember"],
        system_prompt=(
            "You are Theorist. The research question implies some underlying mechanism — your "
            "job is to make it formal so Analyst can test it.\n\n"
            "Tool workflow:\n"
            "1. memory_recall('<topic> mechanism formal model') — existing formalisms.\n"
            "2. tavily_search('<topic> mathematical model') if a formal treatment exists; "
            "   fetch_url() the most promising one.\n\n"
            "Output (use LaTeX-style notation in plain text, e.g. $p(y|x) = ...$):\n"
            "  MECHANISM — what is happening at the model level, in 3-5 sentences.\n"
            "  KEY VARIABLES — name and define each variable that matters (e.g. $N$ = number of "
            "  agents, $p$ = probability of a correct vote, $r$ = round count).\n"
            "  ASSUMPTIONS — list the assumptions the mechanism rests on. These are what Critic "
            "  will attack later.\n"
            "  TESTABLE PREDICTION — what specific quantity should change with what input? "
            "  Phrase as 'If the mechanism holds, we expect $E[\\text{accuracy}|N=k]$ to scale "
            "  as ... ' so Analyst can write code to check.\n\n"
            "memory_remember('<one-line testable prediction>') so other branches can build on it.\n\n"
            "End your turn with: 'THEORY READY — Analyst, run the test.'"
        ),
    ),
    AgentRole(
        name="Analyst",
        role="Quantitative analyst — runs REAL code on REAL data to test the prediction",
        tools=["tavily_search", "fetch_url", "run_code", "memory_recall", "memory_remember",
               "graph_add_entity", "graph_add_link"],
        system_prompt=(
            "You are Analyst. Your job is REAL quantitative analysis. You have:\n"
            " - DataDigger's dataset list (load instructions included)\n"
            " - Theorist's testable prediction in formal terms\n"
            "Combine them.\n\n"
            "Tool workflow:\n"
            "1. Pick the dataset DataDigger surfaced (or construct synthetic data following "
            "   Theorist's mechanism if no real dataset exists).\n"
            "2. Write REAL analytical Python that tests Theorist's prediction. The sandbox has "
            "   ONLY these packages installed (do NOT import others):\n"
            "     numpy, scipy, pandas, scikit-learn, statsmodels, matplotlib, datasets, "
            "     transformers, sentence-transformers, torch, httpx.\n"
            "   Wrap code in ```python ... ``` fences and call run_code(code).\n"
            "   Acceptable: load a real dataset, compute the metric Theorist defined, fit a model, "
            "   run a hypothesis test, sweep a parameter, reproduce a paper's number.\n"
            "   NOT acceptable: `random.choice` loops, toy examples, hello world.\n"
            "3. INSPECT THE OUTPUT. Quote the actual numbers — '$p = 0.034$', '$r^2 = 0.81$', "
            "   'mean accuracy = 0.62 ± 0.04'. Compare to Theorist's prediction.\n"
            "4. graph_add_entity for each paper you cite, graph_add_link for relations.\n"
            "5. memory_remember('<key quantitative result>') so siblings can use it.\n\n"
            "If the prediction is supported, state effect size + uncertainty. If it's refuted, "
            "say so plainly and quote the contradicting number.\n\n"
            "End your turn with: 'ANALYSIS COMPLETE — Innovator, propose alternatives.'"
        ),
    ),
    AgentRole(
        name="Innovator",
        role="Alternative hypothesis generator — proposes contrarian framings before Critic",
        tools=["tavily_search", "fetch_url", "memory_recall", "graph_search"],
        system_prompt=(
            "You are Innovator. Before Critic stress-tests the work, you propose ALTERNATIVES "
            "the team may have missed. The point is to widen the solution space, not just "
            "rubber-stamp what Analyst found.\n\n"
            "Tool workflow:\n"
            "1. memory_recall('<topic> alternative') — has another branch already proposed one?\n"
            "2. tavily_search('<topic> contrarian view') or '<topic> critique' — find 1-2 papers "
            "   that argue the OPPOSITE of the current line. fetch_url() one of them.\n"
            "3. graph_search() to find disconnected entities that suggest a different framing.\n\n"
            "Output:\n"
            "  ALTERNATIVE 1 — a specific competing hypothesis ('what if it's not X but Y?'). "
            "  Include 1 supporting reference if you found one.\n"
            "  ALTERNATIVE 2 — a different framing of the question itself ('we've been asking "
            "  about A, but the more important question may be B'). 1-2 sentences.\n"
            "  WHICH IS MOST DANGEROUS — say which alternative would change the conclusion if true, "
            "  and what evidence would distinguish it from the main hypothesis.\n\n"
            "End your turn with: 'ALTERNATIVES SURFACED — Critic, take it from here.'"
        ),
    ),
    AgentRole(
        name="Critic",
        role="Research critic & rapporteur — challenges, escalates, produces final structured summary",
        tools=["tavily_search", "fetch_url", "memory_recall", "graph_neighbors", "send_message"],
        system_prompt=(
            "You are Critic. By the time you speak, the team has produced: a literature survey "
            "(Surveyor), a dataset list (DataDigger), a formal mechanism (Theorist), code-verified "
            "results (Analyst), and alternative hypotheses (Innovator). Your job has two parts: "
            "stress-test, then aggregate into the final structured summary.\n\n"
            "Stress-test workflow:\n"
            "1. Pick the WEAKEST link across the previous turns:\n"
            "   - Surveyor cited a paper that doesn't actually say what they claim (fetch_url to verify).\n"
            "   - DataDigger's dataset doesn't actually have the field Analyst used.\n"
            "   - Theorist's assumption is implausible — does it hold for the actual data?\n"
            "   - Analyst's sample size is too small for the effect size claimed.\n"
            "   - Innovator's alternative is more compelling than the main hypothesis.\n"
            "2. graph_neighbors('<key paper>') — look for connected entities that contradict.\n"
            "3. memory_recall('<key claim>') — has another branch already refuted this?\n"
            "4. If you find a contradiction with another team's work, send_message(to_team='<branch_id>', "
            "   subject='contradiction', content='<details>') so they see it next turn.\n\n"
            "Final output (be DETAILED, no truncation — this gets written into the paper):\n\n"
            "FINDINGS — 3-5 bullets. Each line:\n"
            "  - Specific claim with the exact number from Analyst.\n"
            "  - Citation: [Author, Year, URL].\n"
            "  - Confidence: high / medium / low (with one sentence why).\n\n"
            "CODE — paste Analyst's Python verbatim and its literal output. Do NOT summarize. "
            "If numbers were quoted, keep them.\n\n"
            "ALTERNATIVES — restate Innovator's alternatives + what evidence distinguishes them. "
            "If you've now ruled one out, say so.\n\n"
            "OPEN QUESTIONS — 1-3 follow-ups for the NEXT depth level. For each:\n"
            "  - Specific question.\n"
            "  - novelty_score (0-1): >0.7 if a genuinely new angle (these will spawn children), "
            "  <0.5 if obvious / already covered (these will be pruned).\n"
            "  - One-sentence rationale.\n\n"
            "PAPER PARTS — substantial paragraphs (5+ sentences each) for sections this branch "
            "contributes to. Use this exact structure:\n"
            "  ## introduction — context for this sub-question.\n"
            "  ## findings — quantitative results from Analyst, with the actual numbers, citations, "
            "  and the dataset DataDigger used.\n"
            "  ## discussion — what the result means, in light of Theorist's mechanism and "
            "  Innovator's alternatives.\n\n"
            "End with the literal token TERMINATE on its own line."
        ),
    ),
]


class ExplorationConfig(BaseModel):
    agents: list[AgentRole] = Field(default_factory=lambda: list(DEFAULT_AGENTS))
    max_depth: int = Field(default=4, ge=1, le=100)
    max_concurrent: int = Field(default=8, ge=1, le=16)
    services: list[str] = Field(default=["memory", "communication"])
    model: str = Field(default="google/gemini-3-flash-preview")
    api_type: str = Field(default="openai")
    base_url: str = Field(default="https://openrouter.ai/api/v1")
    api_key_env: str = Field(default="GEMINI_API_KEY")


class Citation(BaseModel):
    title: str = Field(description="Paper/source title")
    authors: str = Field(default="", description="Author names")
    year: str = Field(default="", description="Publication year")
    url: str = Field(default="", description="URL or DOI if available")
    relevance: str = Field(default="", description="Why this source matters for the claim")


class Finding(BaseModel):
    claim: str
    evidence: str
    citations: list[Citation] = Field(default_factory=list, description="Academic citations supporting this finding")
    novelty: str = Field(default="", description="How novel is this finding vs prior art")
    confidence: float = Field(
        default=0.5, ge=0, le=1,
        description="0-1. Boost when: real citation present, code verification ran, cross-branch corroboration. Penalize when: no source, weak evidence, contradicted elsewhere.",
    )
    code_ref: str | None = Field(default=None, description="Reference to a code block that supports this finding")
    spawned_child: str | None = None


class OpenQuestion(BaseModel):
    question: str
    novelty_score: float = Field(ge=0, le=1)
    reason: str = ""


class CodeBlock(BaseModel):
    code: str = Field(description="Python code to execute for verification")
    purpose: str = Field(description="What this code tests or analyzes")
    interpretation: str = Field(description="What the output means for the research question")


class ExplorationNode(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    topic: str
    depth: int = 0
    parent_id: str | None = None
    status: NodeStatus = NodeStatus.PENDING
    sandbox_id: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    agent_log: list[str] = Field(default_factory=list)
    code_blocks: list[dict] = Field(default_factory=list)  # {code, output, exit_code}


class ExplorationTree(BaseModel):
    root_id: str
    nodes: dict[str, ExplorationNode] = Field(default_factory=dict)
    max_depth: int = 3
    max_concurrent: int = 4
    topic: str = ""


# ---------------------------------------------------------------------------
# Structured output produced by the explorer agent
# ---------------------------------------------------------------------------


class PaperPart(BaseModel):
    section: str = Field(description="One of: abstract, introduction, methodology, findings, discussion, conclusion")
    content: str = Field(description="Draft content for this section based on what was discovered")
    sources: list[str] = Field(default_factory=list, description="Sources cited in this part")
    confidence: float = Field(default=0.5, ge=0, le=1, description="How confident you are in this section")


class ExplorationResult(BaseModel):
    summary: str = Field(description="1-2 sentence summary of what was discovered")
    findings: list[Finding] = Field(description="Key findings from this exploration")
    code_blocks: list[CodeBlock] = Field(
        default_factory=list,
        description="Code to execute for verification. Keep simple — pandas, math, string analysis.",
    )
    open_questions: list[OpenQuestion] = Field(
        description="Questions worth investigating further. Set novelty_score > 0.7 for genuinely novel directions, < 0.5 for obvious/already-covered."
    )
    pivot: str | None = Field(
        default=None,
        description="If the evidence contradicts the initial hypothesis, describe the pivot",
    )
    paper_parts: list[PaperPart] = Field(
        default_factory=list,
        description="Contribute to the research paper. Each finding should generate a paper_part for the relevant section (findings, discussion, etc).",
    )


# ---------------------------------------------------------------------------
# Quality evaluation model
# ---------------------------------------------------------------------------


class Contradiction(BaseModel):
    branch_a: str = Field(description="Identifier of one branch making a claim")
    branch_b: str = Field(description="Identifier of another branch making a conflicting claim")
    claim_a: str = Field(description="The claim from branch A")
    claim_b: str = Field(description="The conflicting claim from branch B")
    suggested_resolution: str = Field(default="", description="How to resolve, or what evidence is needed")


class Gap(BaseModel):
    topic: str = Field(description="What aspect of the research question was not addressed")
    importance: str = Field(default="medium", description="high | medium | low")


class CrossCheckReport(BaseModel):
    contradictions: list[Contradiction] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    redundancies: list[str] = Field(default_factory=list, description="Findings that appear in multiple branches and should be merged")
    summary: str = Field(default="", description="One-paragraph synthesis of the cross-check")


class CorrectionItem(BaseModel):
    issue: str = Field(description="What was wrong in the draft")
    fix: str = Field(description="How it was corrected in the revised version")
    severity: str = Field(default="medium", description="high | medium | low")


class SelfCorrectionReport(BaseModel):
    corrections_applied: list[CorrectionItem] = Field(default_factory=list)
    revised_paper: str = Field(description="The full revised paper in markdown")
    limitations: list[str] = Field(default_factory=list, description="What could not be verified")


class QualityMetrics(BaseModel):
    citation_count: int = Field(description="Number of real citations referenced")
    novelty_score: float = Field(ge=0, le=1, description="How novel are the findings vs existing literature")
    evidence_quality: float = Field(ge=0, le=1, description="Proportion of claims backed by evidence or code verification")
    contradiction_count: int = Field(description="Number of identified contradictions across branches")
    correction_count: int = Field(description="Number of self-corrections made during exploration")
    coverage_score: float = Field(ge=0, le=1, description="How thoroughly the topic was explored (breadth × depth)")
    paper_completeness: float = Field(ge=0, le=1, description="Are all paper sections (abstract through conclusion) adequately filled?")
    verdict: str = Field(description="One-line quality assessment: publishable / needs work / insufficient")


# ---------------------------------------------------------------------------
# Shared knowledge — backed by khive Python SDK
# ---------------------------------------------------------------------------


class SharedKnowledge:
    """Cross-node knowledge store backed by khive Python SDK."""

    def __init__(self, services: list[str] | None = None, tree_id: str = "") -> None:
        from khive import Khive

        self._tree_id = tree_id
        self._services = services or []
        self._client = Khive(
            api_key=os.environ.get("KHIVE_API_KEY", ""),
            base_url=os.environ.get("KHIVE_BASE_URL", "https://khive-mcp.fly.dev"),
            namespace=f"explore:{tree_id}" if tree_id else "lionag2-demo",
        )

    def memory_remember(self, fact: str) -> None:
        """Store a fact in khive persistent memory."""
        try:
            self._client.memory.remember(content=fact, memory_type="semantic")
        except Exception as exc:
            logger.warning("khive memory.remember failed: %s", exc)

    def memory_recall(self, query: str, limit: int = 10) -> str:
        """Recall facts from khive memory via semantic search."""
        try:
            result = self._client.memory.recall(query=query, limit=limit)
            items = getattr(result, 'items', []) or []
            if not items:
                return ""
            return "\n".join(
                getattr(item, 'content', str(item))
                for item in items[:limit]
            )
        except Exception as exc:
            logger.warning("khive memory.recall failed: %s", exc)
            return ""


# ---------------------------------------------------------------------------
# Code execution (local, restricted subprocess)
# ---------------------------------------------------------------------------


def _execute_code(code: str) -> tuple[str, int]:
    """Execute Python code in a restricted subprocess with a 10 s timeout."""
    try:
        result = subprocess.run(  # noqa: S603
            ["python3", "-c", code],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
            env={"PATH": "/usr/bin:/usr/local/bin"},
        )
        output = result.stdout[:1000]
        if result.stderr:
            output += f"\nSTDERR: {result.stderr[:500]}"
        return output, result.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT: execution exceeded 10s", 1
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}", 1


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


from .agent_tools import make_tools, tavily_search_sync  # noqa: E402


def _build_explore_prompt(
    node: ExplorationNode,
    context: str,
    tree: ExplorationTree,
) -> str:
    parts = [f"# Research topic\n{node.topic}\n"]
    parts.append(f"# Exploration depth: {node.depth} / {tree.max_depth}")

    if node.depth == 0:
        parts.append(
            "## Depth guidance — this is the ROOT exploration\n"
            "Goal: map the territory. Find the canonical sources AND at least 2 sources that DISAGREE "
            "with the consensus. Identify alternative framings of the question. The Critic must "
            "propose at least one alternative hypothesis."
        )
    elif node.depth == 1:
        parts.append(
            "## Depth guidance — this is depth=1, a sub-investigation\n"
            "Goal: go DEEPER, not broader. The parent already surveyed the field — your job is to "
            "drill into the specific sub-claim or mechanism named above. Skip generic surveys; "
            "find papers that get into the implementation details, edge cases, or empirical "
            "ablations. Your code should test the specific mechanism, not the general claim."
        )
    else:
        parts.append(
            f"## Depth guidance — this is depth={node.depth}, a fine-grained investigation\n"
            "Goal: empirical specifics. Find narrow results: an ablation, a reproduction, a single "
            "dataset's behavior, a particular failure mode. Open questions you spawn from here "
            "should be VERY targeted (low novelty is fine — at this depth we're confirming or "
            "ruling out specific mechanisms)."
        )

    if context:
        parts.append(
            "\n## Prior findings from parent branches (USE these — don't redo their work)\n"
            f"{context}\n\n"
            "If your evidence CONTRADICTS any prior finding listed above, explicitly flag this as "
            "a PIVOT in your output and explain the correction."
        )

    if node.depth > 0:
        parts.append(
            "\n## This is a sub-investigation spawned by an open question from a parent node.\n"
            "Treat the topic above as a NARROW question. Don't broaden the scope. The parent "
            "already covered the breadth — your contribution is depth on this specific angle."
        )

    parts.append(
        "\n## Process requirements\n"
        "- Surveyor: use tavily_search + fetch_url to read REAL pages, list 8-12 sources with "
        "  proper citations, identify alternative framings.\n"
        "- Analyst: write REAL Python (numpy/scipy/pandas/sklearn) that analyzes a REAL dataset "
        "  or reproduces a paper's result. Quote the actual numerical output. Build the knowledge graph.\n"
        "- Critic: stress-test the weakest claim, propose at least one alternative hypothesis, "
        "  produce the final structured summary."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Core exploration unit
# ---------------------------------------------------------------------------


async def _run_team_exploration(
    node: ExplorationNode,
    context: str,
    tree: ExplorationTree,
    queue: asyncio.Queue,
    knowledge: SharedKnowledge,
    config: ExplorationConfig,
) -> ExplorationResult | None:
    """Run a multi-agent team on one exploration node via AG2 GroupChat."""
    # Tools defined in agent_tools.py (no future annotations — safe for function_to_schema)
    tool_registry = make_tools(knowledge)

    agent_configs = []

    for i, agent_role in enumerate(config.agents):
        is_last = i == len(config.agents) - 1
        handoffs = []
        if not is_last:
            next_name = config.agents[i + 1].name
            handoffs.append({
                "target": next_name,
                "condition": f"When {agent_role.name} has completed their part",
            })

        system = agent_role.system_prompt
        if context:
            system += f"\n\nPrior findings from parent branches:\n{context}"

        agent_configs.append({
            "name": agent_role.name,
            "role": agent_role.role,
            "system_message": system + "\nBe concise — max 4 sentences per turn.",
            "tools": agent_role.tools,
            "handoffs": handoffs,
        })

    # Emit team composition event
    await queue.put({
        "type": "team_active",
        "node_id": node.id,
        "agents": [
            {"name": a.name, "role": a.role, "tools": a.tools}
            for a in config.agents
        ],
        "timestamp": time.time(),
    })

    # Run GroupChat via lionagi AG2 endpoint
    # NOTE: tool_registry must NOT go through iModel kwargs — it leaks into
    # EndpointConfig.kwargs and lionagi tries to register_tools on them.
    # Set it directly on the endpoint after construction.
    model = li.iModel(
        provider="ag2",
        endpoint="group_chat",
        agent_configs=agent_configs,
        llm_config={
            "config_list": [{
                "model": config.model,
                "api_key": os.environ.get(config.api_key_env, ""),
                "base_url": config.base_url,
                "default_headers": {
                    "HTTP-Referer": "https://khive.ai",
                    "X-Title": "lionag2",
                },
            }],
        },
    )
    model.endpoint._tool_registry = tool_registry

    prompt = _build_explore_prompt(node, context, tree)
    prompt += (
        "\n\nProduce a structured research result. The last agent (Critic) must provide "
        "the final summary including: findings with citations, code blocks for verification, "
        "open questions for further investigation, and paper_parts for the research paper."
    )

    # Stream chunks directly from the endpoint so we can emit per-agent SSE events
    transcript_parts: list[str] = []
    async for chunk in model.endpoint.stream({"prompt": prompt}):
        ctype = getattr(chunk, "type", None)
        agent = (chunk.metadata or {}).get("agent") if hasattr(chunk, "metadata") else None
        content = getattr(chunk, "content", None)

        if ctype == "text" and content:
            transcript_parts.append(f"[{agent}] {content}")
            await queue.put({
                "type": "agent_message",
                "node_id": node.id,
                "agent": agent or "unknown",
                "content": content,
                "timestamp": time.time(),
            })
        elif ctype == "tool_use":
            tool_name = getattr(chunk, "tool_name", None)
            tool_input = getattr(chunk, "tool_input", None)
            await queue.put({
                "type": "tool_call",
                "node_id": node.id,
                "agent": agent or "unknown",
                "tool": tool_name,
                "args": str(tool_input) if tool_input else "",
                "timestamp": time.time(),
            })
            transcript_parts.append(f"[{agent} → {tool_name}({str(tool_input)})]")
        elif ctype == "tool_result":
            tool_output = getattr(chunk, "tool_output", None)
            await queue.put({
                "type": "tool_result",
                "node_id": node.id,
                "agent": agent or "unknown",
                "output": str(tool_output) if tool_output else "",
                "timestamp": time.time(),
            })
            transcript_parts.append(f"[tool_result] {str(tool_output)}")
        elif ctype == "system" and content:
            await queue.put({
                "type": "speaker_change",
                "node_id": node.id,
                "info": content,
                "timestamp": time.time(),
            })

    transcript = "\n".join(transcript_parts)
    node.agent_log.append(f"groupchat transcript ({len(transcript)} chars)")

    if not transcript.strip():
        return ExplorationResult(
            summary="GroupChat produced no output",
            findings=[],
            open_questions=[],
        )

    # Convert transcript → structured ExplorationResult via a second LLM call
    structurer = li.Branch(
        chat_model=li.iModel(provider="openrouter", model="google/gemini-3-flash-preview"),
        system=(
            "You convert a multi-agent research conversation into a structured ExplorationResult. "
            "Extract concrete findings (claim + evidence + citations), code blocks the agents wrote, "
            "open questions worth pursuing, and paper sections. Be honest: if the agents didn't "
            "actually find sources or write code, return empty lists rather than fabricating content. "
            "If a citation has no URL or year, leave those fields empty."
        ),
    )
    try:
        structured = await structurer.communicate(
            instruction=(
                f"Research topic: {node.topic}\n\n"
                f"Multi-agent conversation transcript:\n```\n{transcript}\n```\n\n"
                "Convert this into an ExplorationResult."
            ),
            response_format=ExplorationResult,
        )
        if isinstance(structured, ExplorationResult):
            return structured
        if isinstance(structured, dict):
            return ExplorationResult.model_validate(structured)
    except Exception as exc:
        logger.warning("Structuring failed for node %s: %s", node.id, exc)

    return ExplorationResult(
        summary=transcript,
        findings=[Finding(claim=transcript, evidence="GroupChat transcript (unstructured)", citations=[])],
        open_questions=[],
    )


async def explore_node(
    node: ExplorationNode,
    tree: ExplorationTree,
    queue: asyncio.Queue,
    knowledge: SharedKnowledge,
) -> None:
    """Run one exploration node — the recursive unit of work."""

    node.status = NodeStatus.ACTIVE
    await queue.put(
        {
            "type": "node_active",
            "node_id": node.id,
            "topic": node.topic,
            "depth": node.depth,
            "timestamp": time.time(),
        }
    )

    # 1. Gather context from parent branches (via shared knowledge)
    context = ""
    if node.parent_id:
        parent_findings = knowledge.memory_recall(node.topic)
        if parent_findings:
            context = f"Prior research findings:\n{parent_findings}"
            await queue.put(
                {
                    "type": "node_recall",
                    "node_id": node.id,
                    "recalled": parent_findings,
                    "timestamp": time.time(),
                }
            )

    # 2. Run agent team (GroupChat or single agent based on config)
    config = getattr(tree, '_config', None) or ExplorationConfig()

    await queue.put({
        "type": "node_searching",
        "node_id": node.id,
        "agents": [a.name for a in config.agents],
        "timestamp": time.time(),
    })

    # Always use AG2 GroupChat — no fallback, debug properly
    result = await _run_team_exploration(node, context, tree, queue, knowledge, config)

    # Normalise result — operate() returns BaseModel | dict | str | list | None
    if isinstance(result, ExplorationResult):
        exploration = result
    elif isinstance(result, dict):
        exploration = ExplorationResult.model_validate(result)
    else:
        # Last resort: attempt JSON parse from string representation
        try:
            exploration = ExplorationResult.model_validate_json(str(result))
        except Exception:  # noqa: BLE001
            logger.warning(
                "[explore_node] Failed to parse ExplorationResult for node %s; using empty result",
                node.id,
            )
            exploration = ExplorationResult(
                summary=str(result),
                findings=[],
                open_questions=[],
            )

    node.agent_log.append(f"summary: {exploration.summary}")

    # Collect paper parts
    for pp in exploration.paper_parts:
        await queue.put({
            "type": "paper_part",
            "node_id": node.id,
            "section": pp.section,
            "content": pp.content,
            "confidence": pp.confidence,
            "timestamp": time.time(),
        })

    if exploration.pivot:
        node.agent_log.append(f"pivot: {exploration.pivot}")
        await queue.put(
            {
                "type": "pivot",
                "node_id": node.id,
                "pivot": exploration.pivot,
                "timestamp": time.time(),
            }
        )

    # 3. Process findings
    for f in exploration.findings:
        node.findings.append(f)
        knowledge.memory_remember(f"{node.topic}: {f.claim}")
        await queue.put(
            {
                "type": "finding",
                "node_id": node.id,
                "claim": f.claim,
                "evidence": f.evidence,
                "timestamp": time.time(),
            }
        )

    # 4. Code execution
    for code_block in exploration.code_blocks:
        await queue.put(
            {
                "type": "code_start",
                "node_id": node.id,
                "code": code_block.code,
                "purpose": code_block.purpose,
                "timestamp": time.time(),
            }
        )

        output, exit_code = _execute_code(code_block.code)
        node.code_blocks.append({"code": code_block.code, "output": output, "exit_code": exit_code})

        await queue.put(
            {
                "type": "code_result",
                "node_id": node.id,
                "output": output,
                "exit_code": exit_code,
                "timestamp": time.time(),
            }
        )

        # If code has a meaningful interpretation, promote it to a finding
        if code_block.interpretation:
            node.findings.append(
                Finding(
                    claim=code_block.interpretation,
                    evidence=f"Code output: {output}",
                    code_ref=code_block.code,
                )
            )
            knowledge.memory_remember(f"{node.topic}: {code_block.interpretation}")

    # 5. Evaluate open questions for spawning
    existing_topics = [n.topic.lower() for n in tree.nodes.values()]

    for q in exploration.open_questions:
        node.open_questions.append(q)

        if q.novelty_score >= 0.7 and node.depth < tree.max_depth:
            # Dedup check — avoid re-exploring already-queued topics
            q_prefix = q.question.lower()[:30]
            if not any(q_prefix in t for t in existing_topics):
                child = ExplorationNode(
                    topic=q.question,
                    depth=node.depth + 1,
                    parent_id=node.id,
                )
                tree.nodes[child.id] = child
                node.children.append(child.id)
                # Update existing_topics so the next question in the same batch
                # doesn't spawn a near-duplicate
                existing_topics.append(child.topic.lower())

                await queue.put(
                    {
                        "type": "child_spawned",
                        "parent_id": node.id,
                        "child_id": child.id,
                        "question": q.question,
                        "novelty_score": q.novelty_score,
                        "depth": child.depth,
                        "timestamp": time.time(),
                    }
                )
            else:
                await queue.put(
                    {
                        "type": "node_pruned",
                        "node_id": node.id,
                        "question": q.question,
                        "reason": "duplicate",
                        "timestamp": time.time(),
                    }
                )
        else:
            reason = (
                f"novelty too low ({q.novelty_score:.2f})"
                if q.novelty_score < 0.7
                else f"max depth reached ({tree.max_depth})"
            )
            await queue.put(
                {
                    "type": "node_pruned",
                    "node_id": node.id,
                    "question": q.question,
                    "reason": reason,
                    "timestamp": time.time(),
                }
            )

    node.status = NodeStatus.COMPLETE
    await queue.put(
        {
            "type": "node_complete",
            "node_id": node.id,
            "finding_count": len(node.findings),
            "children_count": len(node.children),
            "timestamp": time.time(),
        }
    )


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


async def _cross_check(
    tree: ExplorationTree,
    queue: asyncio.Queue,
    knowledge: SharedKnowledge,
) -> str:
    """Cross-section correction: identify contradictions and gaps across branches."""
    await queue.put({"type": "cross_check_start", "timestamp": time.time()})

    branch_summaries: list[str] = []
    for node in tree.nodes.values():
        if node.status != NodeStatus.COMPLETE or not node.findings:
            continue
        findings_text = "\n".join(f"  - {f.claim}" for f in node.findings)
        branch_summaries.append(
            f"Branch [{node.id}] (depth {node.depth}): {node.topic}\n{findings_text}"
        )

    if not branch_summaries:
        return ""

    reviewer = li.Branch(
        chat_model=li.iModel(provider="openrouter", model="google/gemini-3-flash-preview"),
        system=CROSS_CHECK_SYSTEM,
    )
    try:
        report = await reviewer.communicate(
            instruction=(
                f"Research topic: {tree.topic}\n\n"
                f"Findings from {len(branch_summaries)} branches:\n\n"
                + "\n\n".join(branch_summaries)
                + "\n\nIdentify contradictions, gaps, redundancies. Return a structured CrossCheckReport."
            ),
            response_format=CrossCheckReport,
        )
        if isinstance(report, dict):
            report = CrossCheckReport.model_validate(report)
        if not isinstance(report, CrossCheckReport):
            report = CrossCheckReport(summary=str(report))
    except Exception as exc:
        logger.warning("Cross-check structured failed: %s — falling back to free-text", exc)
        free = await reviewer.communicate(
            instruction=(
                f"Research topic: {tree.topic}\n\n"
                + "\n\n".join(branch_summaries)
                + "\n\nIdentify contradictions, gaps, and corrections."
            ),
        )
        report = CrossCheckReport(summary=str(free))

    corrections_text = report.model_dump_json(indent=2)

    await queue.put({
        "type": "cross_check",
        "corrections": corrections_text,
        "report": report.model_dump(),
        "timestamp": time.time(),
    })

    knowledge.memory_remember(f"Cross-check: {report.summary}")
    return corrections_text


async def _write_paper(
    tree: ExplorationTree,
    queue: asyncio.Queue,
    corrections: str,
) -> str:
    """Aggregate paper parts, generate final paper, produce LaTeX → PDF."""
    await queue.put({"type": "synthesis_start", "timestamp": time.time()})

    # Build a structured per-node payload for the paper writer
    structured_nodes: list[str] = []
    all_findings_count = 0
    all_citations: list[str] = []
    all_code_blocks: list[str] = []
    pivots: list[str] = []

    for node in sorted(tree.nodes.values(), key=lambda n: (n.depth, n.topic)):
        if node.status != NodeStatus.COMPLETE:
            continue

        node_lines = [f"\n### NODE [depth={node.depth}]: {node.topic}"]
        for i, f in enumerate(node.findings, 1):
            all_findings_count += 1
            confidence = getattr(f, "confidence", 0.5)
            node_lines.append(f"\nFINDING {i}: {f.claim}")
            node_lines.append(f"  Evidence: {f.evidence}")
            node_lines.append(f"  Confidence: {confidence:.2f}")
            if f.novelty:
                node_lines.append(f"  Novelty: {f.novelty}")
            if f.citations:
                node_lines.append("  Citations:")
                for c in f.citations:
                    cite_str = f"    - {c.title}"
                    if c.authors:
                        cite_str += f" ({c.authors}"
                        if c.year:
                            cite_str += f", {c.year}"
                        cite_str += ")"
                    elif c.year:
                        cite_str += f" ({c.year})"
                    if c.url:
                        cite_str += f" {c.url}"
                    if c.relevance:
                        cite_str += f" — {c.relevance}"
                    node_lines.append(cite_str)
                    all_citations.append(cite_str.strip())
            if f.code_ref:
                node_lines.append(f"  Code reference:\n```python\n{f.code_ref}\n```")

        for cb in node.code_blocks:
            code_str = cb.get("code", "")
            output = cb.get("output", "")
            if code_str:
                node_lines.append(f"\nCODE EXECUTED:\n```python\n{code_str}\n```\nOUTPUT:\n```\n{output}\n```")
                all_code_blocks.append(code_str)

        for log_line in node.agent_log:
            if log_line.startswith("pivot:"):
                pivots.append(f"[{node.topic}] {log_line}")

        structured_nodes.append("\n".join(node_lines))

    if all_findings_count == 0:
        await queue.put({"type": "synthesis", "text": "No findings.", "timestamp": time.time()})
        await queue.put({"type": "exploration_done", "total_nodes": len(tree.nodes), "total_findings": 0, "max_depth_reached": 0, "timestamp": time.time()})
        return ""

    # Final paper assembly via LLM
    writer = li.Branch(
        chat_model=li.iModel(provider="openrouter", model="google/gemini-3-flash-preview"),
        system=PAPER_SYSTEM,
    )

    instruction_parts = [
        f"# Research question\n{tree.topic}\n",
        f"# Exploration stats",
        f"- Total nodes: {len(tree.nodes)}",
        f"- Total findings: {all_findings_count}",
        f"- Total citations gathered: {len(all_citations)}",
        f"- Code executions: {len(all_code_blocks)}",
        f"- Max depth reached: {max((n.depth for n in tree.nodes.values()), default=0)}",
        f"\n# Per-node research payload (use this to construct the paper):",
        "\n".join(structured_nodes),
    ]
    if pivots:
        instruction_parts.append(f"\n# Pivots (hypothesis contradictions):\n" + "\n".join(pivots))
    if corrections:
        instruction_parts.append(f"\n# Cross-section corrections from reviewer:\n{corrections}")
    instruction_parts.append(
        "\n# Your task\n"
        "Write the full research paper following the structure in your system prompt. "
        "Be substantial: 3000-5000 words. Cite all the sources listed above (you should reach 30+ citations). "
        "Use markdown sections (## Abstract, ## 1. Introduction, ## 2. Background and Related Work, ## 3. Methodology, "
        "## 4. Findings, ## 5. Discussion, ## 6. Limitations, ## 7. Conclusion, ## References). "
        "Include LaTeX math where helpful ($...$, $$...$$). Include the code blocks and their outputs in the Findings section. "
        "Build a numbered bibliography in the References section."
    )

    result = await writer.communicate(instruction="\n".join(instruction_parts))
    paper_text = str(result)

    await queue.put({"type": "synthesis", "text": paper_text, "timestamp": time.time()})

    # Self-correction pass: re-read the synthesis and fix internal contradictions, weak claims, missing evidence
    paper_text = await _self_correct(tree, paper_text, queue)

    # Generate LaTeX and compile to PDF
    pdf_path = await _generate_pdf(tree.topic, paper_text, queue)

    max_depth = max((n.depth for n in tree.nodes.values()), default=0)
    await queue.put({
        "type": "exploration_done",
        "total_nodes": len(tree.nodes),
        "total_findings": all_findings_count,
        "max_depth_reached": max_depth,
        "pdf_path": pdf_path,
        "timestamp": time.time(),
    })
    return paper_text


async def _self_correct(
    tree: ExplorationTree,
    paper_text: str,
    queue: asyncio.Queue,
) -> str:
    """Verifier pass: identify and fix internal contradictions, weak claims,
    and unsourced numbers. Returns a revised paper plus a structured list of corrections.
    """
    await queue.put({"type": "self_correct_start", "timestamp": time.time()})

    verifier = li.Branch(
        chat_model=li.iModel(provider="openrouter", model="google/gemini-3-flash-preview"),
        system=(
            "You are a research verifier. Read the draft paper and identify: "
            "(a) internal contradictions, (b) claims without evidence, (c) citations that look fabricated, "
            "(d) numerical statements that aren't sourced. "
            "Produce a REVISED paper that fixes these issues, plus a structured list of corrections. "
            "Keep the same section structure (## Abstract, ## 1. Introduction, ...). "
            "Soften unsupported claims ('preliminary evidence suggests') rather than deleting them. "
            "Include a ## Limitations section listing what could not be verified."
        ),
    )

    try:
        report = await verifier.communicate(
            instruction=(
                f"Topic: {tree.topic}\n\n"
                f"Draft paper:\n```\n{paper_text}\n```\n\n"
                "Return a SelfCorrectionReport with the corrections applied and the full revised paper "
                "in `revised_paper` (markdown, with ## Limitations section)."
            ),
            response_format=SelfCorrectionReport,
        )
        if isinstance(report, dict):
            report = SelfCorrectionReport.model_validate(report)
        if not isinstance(report, SelfCorrectionReport):
            report = SelfCorrectionReport(revised_paper=str(report))
    except Exception as exc:
        logger.warning("Self-correction structured failed: %s — falling back to free-text", exc)
        free = await verifier.communicate(
            instruction=(
                f"Topic: {tree.topic}\n\n"
                f"Draft paper:\n```\n{paper_text}\n```\n\n"
                "Produce the revised paper in markdown. Add ## Limitations at the end."
            ),
        )
        report = SelfCorrectionReport(revised_paper=str(free))

    revised_text = report.revised_paper or paper_text

    await queue.put({
        "type": "self_correct",
        "original_length": len(paper_text),
        "revised_length": len(revised_text),
        "revised": revised_text,
        "corrections": [c.model_dump() for c in report.corrections_applied],
        "limitations": report.limitations,
        "timestamp": time.time(),
    })

    return revised_text


async def _generate_pdf(topic: str, paper_text: str, queue: asyncio.Queue) -> str | None:
    """Convert paper markdown to LaTeX and compile to PDF."""
    import tempfile
    from pathlib import Path

    await queue.put({"type": "pdf_generating", "timestamp": time.time()})

    # Convert markdown sections to LaTeX
    latex_content = _markdown_to_latex(topic, paper_text)

    # Write and compile
    output_dir = Path(__file__).parent.parent / "data" / "papers"
    output_dir.mkdir(parents=True, exist_ok=True)

    import re
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower().strip())[:50]

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / "paper.tex"
        tex_path.write_text(latex_content)

        try:
            result = subprocess.run(  # noqa: S603
                ["pdflatex", "-interaction=nonstopmode", "-output-directory", tmpdir, str(tex_path)],  # noqa: S607
                capture_output=True, text=True, timeout=30,
            )
            pdf_src = Path(tmpdir) / "paper.pdf"
            if pdf_src.exists():
                pdf_dst = output_dir / f"{slug}.pdf"
                import shutil
                shutil.copy2(pdf_src, pdf_dst)
                await queue.put({"type": "pdf_ready", "path": str(pdf_dst), "timestamp": time.time()})
                return str(pdf_dst)
            else:
                logger.warning("pdflatex failed: %s", result.stderr[:500])
                await queue.put({"type": "pdf_ready", "path": "", "error": "pdflatex compilation failed", "timestamp": time.time()})
                return None
        except FileNotFoundError:
            logger.warning("pdflatex not installed — skipping PDF generation")
            await queue.put({"type": "pdf_ready", "path": "", "error": "pdflatex not installed", "timestamp": time.time()})
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("PDF generation failed: %s", exc)
            return None


def _markdown_to_latex(topic: str, markdown: str) -> str:
    """Convert paper markdown to LaTeX, preserving math, code, and citations."""
    import re

    # Step 1: extract code blocks and math regions, replace with placeholders
    placeholders: dict[str, str] = {}

    def stash(text: str, kind: str) -> str:
        token = f"@@{kind}_{len(placeholders)}@@"
        placeholders[token] = text
        return token

    # Fenced code blocks ```lang\n...\n```
    def code_block_repl(m):
        lang = m.group(1) or ""
        body = m.group(2)
        wrapped = (
            "\\begin{verbatim}\n" + body + "\n\\end{verbatim}"
            if not lang or lang in ("output", "text", "")
            else "\\begin{verbatim}\n" + body + "\n\\end{verbatim}"
        )
        return stash(wrapped, "code")

    markdown = re.sub(r"```([a-zA-Z]*)\n(.*?)\n```", code_block_repl, markdown, flags=re.DOTALL)

    # Display math $$...$$
    markdown = re.sub(r"\$\$(.+?)\$\$", lambda m: stash(f"$${m.group(1)}$$", "dmath"), markdown, flags=re.DOTALL)
    # Inline math $...$
    markdown = re.sub(r"(?<!\\)\$([^$\n]+?)\$", lambda m: stash(f"${m.group(1)}$", "imath"), markdown)
    # Inline code `...`
    markdown = re.sub(r"`([^`\n]+?)`", lambda m: stash(f"\\texttt{{{_escape_latex(m.group(1))}}}", "ic"), markdown)

    # Step 2: line-by-line LaTeX conversion (math/code already protected)
    body_lines: list[str] = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            body_lines.append("\\end{itemize}")
            in_list = False

    for line in markdown.split("\n"):
        # Headings
        h2 = re.match(r"^##\s+(.+)$", line)
        h3 = re.match(r"^###\s+(.+)$", line)
        h4 = re.match(r"^####\s+(.+)$", line)
        if h2:
            close_list()
            body_lines.append(f"\\section{{{_escape_latex(h2.group(1))}}}")
            continue
        if h3:
            close_list()
            body_lines.append(f"\\subsection{{{_escape_latex(h3.group(1))}}}")
            continue
        if h4:
            close_list()
            body_lines.append(f"\\subsubsection{{{_escape_latex(h4.group(1))}}}")
            continue

        # Bullets
        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        if bullet:
            if not in_list:
                body_lines.append("\\begin{itemize}")
                in_list = True
            content = bullet.group(1)
            content = re.sub(r"\*\*(.+?)\*\*", lambda m: f"\\textbf{{{_escape_latex(m.group(1))}}}", content)
            body_lines.append(f"\\item {_escape_latex_keep_placeholders(content)}")
            continue

        close_list()

        # Bold inline
        line = re.sub(r"\*\*(.+?)\*\*", lambda m: f"\\textbf{{{_escape_latex(m.group(1))}}}", line)
        body_lines.append(_escape_latex_keep_placeholders(line))

    close_list()
    body = "\n".join(body_lines)

    # Step 3: restore placeholders
    for token, original in placeholders.items():
        body = body.replace(token, original)

    return f"""\\documentclass[11pt]{{article}}
\\usepackage[margin=1in]{{geometry}}
\\usepackage{{hyperref}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{booktabs}}
\\usepackage{{listings}}

\\title{{{_escape_latex(topic)}}}
\\author{{lionag2 — Recursive Multi-Agent Research}}
\\date{{\\today}}

\\begin{{document}}
\\maketitle
\\tableofcontents

{body}

\\end{{document}}
"""


_LATEX_SPECIAL = {
    "&": "\\&",
    "%": "\\%",
    "$": "\\$",
    "#": "\\#",
    "_": "\\_",
    "{": "\\{",
    "}": "\\}",
    "~": "\\textasciitilde{}",
    "^": "\\textasciicircum{}",
    "\\": "\\textbackslash{}",
}


def _escape_latex(text: str) -> str:
    """Escape LaTeX special characters in plain text (does not touch existing TeX commands)."""
    out = []
    for ch in text:
        out.append(_LATEX_SPECIAL.get(ch, ch))
    return "".join(out)


def _escape_latex_keep_placeholders(text: str) -> str:
    """Escape LaTeX special chars but skip @@kind_N@@ placeholder tokens and existing \\command{...} TeX."""
    import re

    parts = re.split(r"(@@\w+_\d+@@|\\[a-zA-Z]+\{[^}]*\})", text)
    return "".join(p if p.startswith("@@") or p.startswith("\\") else _escape_latex(p) for p in parts)


# ---------------------------------------------------------------------------
# Quality evaluation
# ---------------------------------------------------------------------------


async def _evaluate_quality(
    tree: ExplorationTree,
    paper_text: str,
    corrections: str,
    queue: asyncio.Queue,
) -> None:
    """Self-evaluate research quality with structured metrics."""
    await queue.put({"type": "quality_eval_start", "timestamp": time.time()})

    evaluator = li.Branch(
        chat_model=li.iModel(provider="openrouter", model="google/gemini-3-flash-preview"),
        system=(
            "You are a research quality evaluator. Assess the paper based on concrete metrics. "
            "Be honest — don't inflate scores. A score of 0.5 means average, 0.7 means good, 0.9 means excellent."
        ),
    )

    # Count actual metrics from the tree
    total_findings = sum(len(n.findings) for n in tree.nodes.values() if n.status == NodeStatus.COMPLETE)
    total_citations = sum(
        len(f.citations) for n in tree.nodes.values() for f in n.findings
    )
    total_code = sum(len(n.code_blocks) for n in tree.nodes.values())
    pivots = sum(1 for n in tree.nodes.values() for log in n.agent_log if log.startswith("pivot:"))

    result = await evaluator.operate(
        instruction=(
            f"Evaluate this research paper:\n\n{paper_text}\n\n"
            f"Exploration stats: {len(tree.nodes)} nodes, {total_findings} findings, "
            f"{total_citations} citations, {total_code} code verifications, {pivots} pivots\n"
            f"Corrections: {corrections}"
        ),
        response_format=QualityMetrics,
    )

    if isinstance(result, QualityMetrics):
        metrics = result
    elif isinstance(result, dict):
        metrics = QualityMetrics.model_validate(result)
    else:
        try:
            metrics = QualityMetrics.model_validate_json(str(result))
        except Exception:  # noqa: BLE001
            metrics = QualityMetrics(
                citation_count=total_citations,
                novelty_score=0.5, evidence_quality=0.5,
                contradiction_count=0, correction_count=pivots,
                coverage_score=0.5, paper_completeness=0.5,
                verdict="evaluation failed",
            )

    await queue.put({
        "type": "quality_eval",
        "metrics": metrics.model_dump(),
        "timestamp": time.time(),
    })


# ---------------------------------------------------------------------------
# BFS orchestration
# ---------------------------------------------------------------------------


async def _explore_and_collect(
    node: ExplorationNode,
    tree: ExplorationTree,
    queue: asyncio.Queue,
    knowledge: SharedKnowledge,
    pending: list[str],
    active: set[str],
) -> None:
    """Explore one node and push its children onto the pending queue."""
    try:
        await explore_node(node, tree, queue, knowledge)
        for child_id in node.children:
            pending.append(child_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[explore] Node %s failed: %s", node.id, exc)
        await queue.put(
            {
                "type": "node_error",
                "node_id": node.id,
                "error": str(exc),
                "timestamp": time.time(),
            }
        )
        node.status = NodeStatus.PRUNED
    finally:
        active.discard(node.id)


async def run_exploration(
    topic: str,
    queue: asyncio.Queue,
    *,
    max_depth: int = 4,
    max_concurrent: int = 8,
    services: list[str] | None = None,
    config: ExplorationConfig | None = None,
) -> ExplorationTree:
    """Run the full recursive exploration from a root topic.

    Args:
        topic: The research question to explore.
        queue: An asyncio.Queue that receives SSE-style event dicts as exploration
            progresses.  Callers can consume this queue in real time.
        max_depth: Maximum recursion depth for child nodes.
        max_concurrent: Maximum number of nodes explored simultaneously.
        services: Optional list of khive service names for knowledge routing
            (currently reserved — SharedKnowledge is in-process).

    Returns:
        The fully-populated ExplorationTree after synthesis completes.
    """
    topic = (topic or "").strip()
    if not topic:
        await queue.put({"type": "error", "message": "Topic is empty", "timestamp": time.time()})
        raise ValueError("Topic is empty")

    if config is None:
        config = ExplorationConfig(
            max_depth=max_depth,
            max_concurrent=max_concurrent,
            services=services or ["memory", "communication"],
        )

    root = ExplorationNode(topic=topic, depth=0)
    knowledge = SharedKnowledge(services=config.services, tree_id=root.id)
    tree = ExplorationTree(
        root_id=root.id,
        nodes={root.id: root},
        max_depth=config.max_depth,
        max_concurrent=config.max_concurrent,
        topic=topic,
    )
    tree._config = config  # type: ignore[attr-defined]  # attach for explore_node access

    await queue.put(
        {
            "type": "tree_init",
            "root_id": root.id,
            "topic": topic,
            "max_depth": max_depth,
            "timestamp": time.time(),
        }
    )

    # BFS-like exploration with concurrency control via asyncio tasks
    pending: list[str] = [root.id]
    active: set[str] = set()

    while pending or active:
        # Fill slots up to max_concurrent
        while pending and len(active) < max_concurrent:
            node_id = pending.pop(0)
            node = tree.nodes[node_id]
            active.add(node_id)
            asyncio.create_task(_explore_and_collect(node, tree, queue, knowledge, pending, active))

        if active:
            await asyncio.sleep(0.5)  # lightweight poll — avoids tight spin

    # Cross-section correction round
    corrections = await _cross_check(tree, queue, knowledge)

    # Write structured paper (not flat report)
    paper_text = await _write_paper(tree, queue, corrections)

    # Quality evaluation
    await _evaluate_quality(tree, paper_text, corrections, queue)

    return tree
