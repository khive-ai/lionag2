"""Code review pipeline — specialist analysis + structured synthesis.

Architecture:
  - Agents have real tools: file reading, shell commands, code execution
  - Scanner can flag areas for deeper review (optional depth expansion)
  - Synthesis phase aggregates IssueFound events into ReviewReport
  - All agents see the original instruction (carry_instruction=True)

Local tooling:
  - FilesystemToolkit (read_only) — read_file, find_files
  - LocalShellTool (readonly) — grep, git, find, etc.
  - SandboxCodeTool (DockerCodeEnvironment) — run tests, linters
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from autogen.beta import Agent
from autogen.beta.tools import FilesystemToolkit, LocalShellTool, SandboxCodeTool

from ..core import FuzzySchema
from ..engine import Engine, NodeRegistered, SSECallback
from .events import IssueFound, QuestionRaised
from .models import ReviewIssue, ReviewReport
from .prompts import SYNTHESIZER, build_review_roster
from .tools import REVIEW_TOOLS

logger = logging.getLogger("lionag2.review")


def _make_sandbox(image: str = "python:3.12-slim") -> SandboxCodeTool | None:
    try:
        from autogen.beta.extensions.docker import DockerCodeEnvironment

        return SandboxCodeTool(DockerCodeEnvironment(image=image, network_mode="none"))
    except (ImportError, Exception) as exc:
        logger.debug("Docker sandbox unavailable: %s", exc)
        return None


class ReviewEngine(Engine):
    """Multi-specialist code review engine with local tools.

    Pipeline:
        1. Specialist team analyzes code (scanner → logic → security → architecture)
           - Agents can read files, run shell commands, execute code
        2. Optional depth expansion: scanner flags areas → deeper review
        3. Synthesizer aggregates findings into ReviewReport with verdict
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5.4-mini",
        project_path: str | os.PathLike[str] | None = None,
        sandbox: bool = True,
        sandbox_image: str = "python:3.12-slim",
        max_depth: int = 1,
        extra_specialists: list[dict[str, Any]] | None = None,
        on_event: SSECallback | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model,
            max_depth=max_depth,
            on_event=on_event,
            **kwargs,
        )
        self.flow.name = "review"
        self._extra_specialists = extra_specialists or []

        self._project_path = str(project_path) if project_path else os.getcwd()

        self._fs = FilesystemToolkit(base_path=self._project_path, read_only=True)

        from autogen.beta.tools.shell.environment.local import LocalShellEnvironment

        self._shell = LocalShellTool(
            LocalShellEnvironment(
                path=self._project_path,
                readonly=True,
                timeout=30,
            )
        )

        self._sandbox: SandboxCodeTool | None = None
        if sandbox:
            self._sandbox = _make_sandbox(sandbox_image)

    def resolve_tools(self, tool_tags: tuple[str, ...]) -> list:
        tools: list = []
        tags = set(tool_tags)

        if "files" in tags:
            tools.extend(self._fs.tools)
        if "shell" in tags:
            tools.append(self._shell)
        if "run_code" in tags and self._sandbox:
            tools.append(self._sandbox)

        tools.extend(REVIEW_TOOLS)
        return tools

    def make_agent(
        self, spec: dict[str, Any], *, depth: int = 0, node_id: str = ""
    ) -> Agent:
        agent = super().make_agent(spec, depth=depth, node_id=node_id)
        engine = self

        @agent.observer(IssueFound)
        def _on_issue(event: IssueFound) -> None:
            engine._record(event)

        @agent.observer(QuestionRaised)
        def _on_question(event: QuestionRaised) -> None:
            engine._record(event)

        return agent

    async def _run_node(
        self,
        topic: str,
        *,
        depth: int,
        team_name: str,
        node_id: str,
        parent_node_id: str,
    ) -> str:
        instruction = topic
        if parent_node_id and depth > 0:
            parent_issues = [
                i for i in self.flow.items.by_type(IssueFound) if True
            ]
            if parent_issues:
                prior = "\n".join(
                    f"- [{i.source_agent}] [{i.severity}] {i.title}: {i.description}"
                    for i in parent_issues[-10:]
                )
                instruction = (
                    f"{instruction}\n\n"
                    f"# Prior findings (depth {depth - 1}) — drill deeper on these\n{prior}"
                )

        roster = build_review_roster() + self._extra_specialists
        return await self.run_team(
            roster,
            instruction,
            team_name=team_name,
            depth=depth,
            node_id=node_id,
            carry_instruction=True,
        )

    async def _synthesize(self) -> ReviewReport:
        issues = self.flow.items.by_type(IssueFound)
        questions = self.flow.items.by_type(QuestionRaised)

        if not issues and not questions:
            return ReviewReport(
                summary="No issues found.",
                verdict="approve",
                risk_level="none",
            )

        parts: list[str] = []
        if issues:
            parts.append(f"# Issues Found ({len(issues)})\n")
            for i, issue in enumerate(issues, 1):
                loc = f"{issue.file}:{issue.line}" if issue.file else "general"
                parts.append(
                    f"## Issue {i} [{issue.severity}] ({issue.category})\n"
                    f"- Location: {loc}\n"
                    f"- Title: {issue.title}\n"
                    f"- Description: {issue.description}\n"
                    f"- Suggestion: {issue.suggestion}\n"
                    f"- Found by: {issue.source_agent}\n\n"
                )

        if questions:
            parts.append(f"# Questions ({len(questions)})\n")
            for q in questions:
                parts.append(f"- [{q.source_agent}] {q.question}\n")

        synth = Agent(
            "synthesizer",
            prompt=SYNTHESIZER,
            config=self.config,
            response_schema=FuzzySchema(ReviewReport),
        )
        reply = await synth.ask(
            "".join(parts), stream=self.flow.streams["synthesis"]
        )
        try:
            report = await reply.content(retries=2) or ReviewReport(
                summary=reply.body or "", verdict="comment"
            )
        except Exception:
            report = ReviewReport(summary=reply.body or "", verdict="comment")

        if not report.issues:
            report.issues = [
                ReviewIssue(
                    file=i.file,
                    line=i.line,
                    severity=i.severity,
                    category=i.category,
                    title=i.title,
                    description=i.description,
                    suggestion=i.suggestion,
                )
                for i in issues
            ]

        if not report.questions and questions:
            report.questions = [q.question for q in questions]

        return report

    async def run(self, content: str = "", *, context: str = "") -> ReviewReport:
        """Review code, a diff, or a project directory.

        Args:
            content: Code or diff to review. If empty, agents explore
                     the project_path using file/shell tools.
            context: Optional metadata (PR title, description, intent).

        Returns:
            Structured ReviewReport with verdict, issues, and risk level.
        """
        parts: list[str] = []
        if context:
            parts.append(f"# Context\n{context}")

        parts.append(f"# Project path\n{self._project_path}")

        if content.strip():
            parts.append(f"\n# Code to review\n\n```\n{content.strip()}\n```")
        else:
            parts.append(
                "\n# Instructions\n"
                "Use read_file and find_files to explore the project. "
                "Use run_shell_command for grep, git log, git diff, etc."
            )

        instruction = "\n\n".join(parts)

        root_id = uuid.uuid4().hex[:12]
        team_name = f"review_{uuid.uuid4().hex[:6]}"
        self._record(
            NodeRegistered(
                node_id=root_id,
                topic="code_review",
                depth=0,
                stream_name=team_name,
            )
        )

        roster = build_review_roster() + self._extra_specialists
        await self.run_team(
            roster,
            instruction,
            team_name=team_name,
            node_id=root_id,
            carry_instruction=True,
        )

        await self._wait_for_quiescence()
        return await self._synthesize()


async def review(
    content: str = "",
    *,
    model: str = "gpt-5.4-mini",
    project_path: str | None = None,
    context: str = "",
    sandbox: bool = True,
    on_event: SSECallback | None = None,
    **kwargs: Any,
) -> ReviewReport:
    """One-liner entry point for code review.

    Usage:
        # Review a file
        report = await review(open("myfile.py").read())

        # Review a project directory
        report = await review(project_path="/path/to/project")

        # Review a git diff
        report = await review(subprocess.check_output(["git", "diff"]).decode())
    """
    engine = ReviewEngine(
        model=model,
        project_path=project_path,
        sandbox=sandbox,
        on_event=on_event,
        **kwargs,
    )
    return await engine.run(content, context=context)
