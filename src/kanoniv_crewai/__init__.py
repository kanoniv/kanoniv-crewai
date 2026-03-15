"""Cryptographic identity and delegation for CrewAI agents.

Add verifiable agent identity and attenuated delegation to any CrewAI workflow.
Every tool call carries a cryptographic proof of authority.

    pip install kanoniv-crewai

Usage:

    from kanoniv_crewai import DelegatedCrew
    from kanoniv_agent_auth import AgentKeyPair

    root = AgentKeyPair.generate()
    crew = DelegatedCrew(root)

    researcher = crew.add_agent("researcher", scope=["search", "summarize"], max_cost=5.0)
    writer = crew.add_agent("writer", scope=["write"], max_cost=3.0)

    # Every tool call by these agents carries a delegation proof
    # verifiable back to the root authority.
"""

from kanoniv_crewai.core import (
    DelegatedCrew,
    DelegatedAgent,
    DelegatedTool,
    delegated_tool,
)

__all__ = [
    "DelegatedCrew",
    "DelegatedAgent",
    "DelegatedTool",
    "delegated_tool",
]
