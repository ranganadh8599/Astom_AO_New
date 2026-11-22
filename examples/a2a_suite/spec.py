"""Spec types shared by the A2A example suite.

Each agent is *data*: a description plus three skills, each skill carrying keywords and a
short fact block. ``answer()`` is a deterministic keyword matcher, so the suite needs no
model, costs nothing to run, and produces the same reply for the same question — which is
what you want when the thing under test is routing rather than prose quality.

A question outside an agent's skills gets an explicit refusal naming what it does cover,
so a routing test can distinguish "wrong agent was chosen" from "right agent, wrong answer".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from a2a_suite.catalog import AgentEntry, by_id

PROTOCOL_VERSION = "0.3"

_STOPWORDS = frozenset(
    "a an the and or of in on at to for from with about is are was were be been being do "
    "does did doing have has had what which who whom whose when where why how tell me give "
    "please his her their there this that these those it its as by i you we they he she "
    "can could should would will shall may might must not no yes if then than so such".split()
)


@dataclass(frozen=True)
class Skill:
    """One advertised capability: what it answers, and how to detect it."""

    id: str
    name: str
    description: str
    tags: tuple[str, ...]
    keywords: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class AgentSpec:
    """An agent's identity plus everything needed to answer from."""

    id: str
    name: str
    title: str
    description: str
    port: int
    skills: tuple[Skill, ...]
    knowledge_version: str

    @classmethod
    def from_catalog(
        cls,
        agent_id: str,
        *,
        skills: tuple[Skill, ...],
        knowledge_version: str = "2026-Q4",
    ) -> "AgentSpec":
        entry: AgentEntry = by_id(agent_id)
        if not skills:
            raise ValueError(f"{agent_id} declares no skills")
        return cls(
            id=entry.id,
            name=entry.name,
            title=entry.title,
            description=entry.description,
            port=entry.port,
            skills=skills,
            knowledge_version=knowledge_version,
        )

    def card(self, url: str) -> dict[str, Any]:
        base = url.rstrip("/")
        return {
            "name": self.name,
            "description": self.description,
            "url": base,
            "version": "1.0.0",
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "stateTransitionHistory": False,
            },
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "provider": {
                "organization": "A2A Orchestration POC - test suite",
                "url": base,
            },
            "skills": [
                {
                    "id": skill.id,
                    "name": skill.name,
                    "description": skill.description,
                    "tags": list(skill.tags),
                }
                for skill in self.skills
            ],
        }

    def topics(self) -> str:
        return "; ".join(skill.name.lower() for skill in self.skills)


def _tokens(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if word not in _STOPWORDS
    }


def _scored(spec: AgentSpec, query: str) -> list[Skill]:
    words = _tokens(query)
    scored: list[tuple[int, int, Skill]] = []
    for index, skill in enumerate(spec.skills):
        hits = sum(1 for keyword in skill.keywords if keyword in words)
        if hits:
            # -index keeps declaration order for equal scores, so replies are stable.
            scored.append((hits, -index, skill))
    scored.sort(reverse=True)
    return [skill for _, _, skill in scored]


def refusal(spec: AgentSpec) -> str:
    return (
        f"I only cover {spec.title.lower()}. "
        f"Ask me about: {spec.topics()}. "
        f"(Facts current to {spec.knowledge_version}.)"
    )


def answer(spec: AgentSpec, query: str) -> str:
    """Answer from the fact blocks, or refuse and say what is in scope."""
    text = (query or "").strip()
    if not text:
        return f"Ask me about {spec.topics()}."

    matched = _scored(spec, text)
    if not matched:
        return refusal(spec)

    primary = matched[0]
    body = f"{primary.name}\n\n{primary.text}"
    extra = [skill for skill in matched[1:] if skill.id != primary.id][:1]
    if extra:
        body += "\n\n" + f"{extra[0].name}\n\n{extra[0].text}"
    return body.rstrip()
