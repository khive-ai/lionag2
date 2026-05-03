from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TeamSpec(BaseModel):
    id: str = Field(description="Short unique ID, e.g. 'research', 'analysis'")
    name: str = Field(description="Human-readable team name")
    objective: str = Field(description="Specific, measurable deliverable for this team")
    depends_on: list[str] = Field(
        default_factory=list,
        description="IDs of teams whose output this team needs before starting",
    )
    agent_names: list[str] = Field(
        description="Agent names for this team. 2-4 agents. First receives prompt, last terminates.",
    )
    agent_roles: list[str] = Field(
        description="One-line role for each agent, same order as agent_names",
    )
    max_round: int = Field(default=10, gt=0)


class ResearchPlan(BaseModel):
    topic: str = Field(description="The research topic")
    teams: list[TeamSpec] = Field(
        description="Teams forming a DAG. Teams with no depends_on run in parallel.",
    )
    synthesis_instruction: str = Field(
        description="How to merge all team outputs into the final deliverable",
    )


class TeamResult(BaseModel):
    team_id: str
    output: str
    agent_count: int
    rounds_used: int
