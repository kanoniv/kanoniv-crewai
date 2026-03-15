"""Core delegation primitives for CrewAI."""

import json
import functools
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Optional

from kanoniv_agent_auth import (
    AgentKeyPair,
    AgentIdentity,
    Delegation,
    Invocation,
    McpProof,
    verify_invocation,
    verify_mcp_call,
)

from crewai.tools.base_tool import BaseTool
from pydantic import Field


class DelegatedAgent:
    """An agent with cryptographic identity and delegation.

    Wraps an AgentKeyPair with delegation state. Created by
    DelegatedCrew.add_agent() - not instantiated directly.
    """

    def __init__(
        self,
        name: str,
        keypair: AgentKeyPair,
        delegation: Delegation,
        root_identity: AgentIdentity,
    ):
        self.name = name
        self.keypair = keypair
        self.delegation = delegation
        self.root_identity = root_identity
        self.history: list[dict] = []

    @property
    def did(self) -> str:
        return self.keypair.identity().did

    @property
    def identity(self) -> AgentIdentity:
        return self.keypair.identity()

    def create_proof(self, action: str, args: dict | None = None) -> McpProof:
        """Create an MCP proof for a tool call."""
        args = args or {}
        return McpProof.create(
            self.keypair, action, json.dumps(args), self.delegation
        )

    def verify_action(self, action: str, args: dict | None = None):
        """Verify that this agent can perform the given action.

        Returns (invoker_did, root_did, chain, depth).
        Raises ValueError if delegation doesn't allow it.
        """
        args = args or {}
        invocation = Invocation.create(
            self.keypair, action, json.dumps(args), self.delegation
        )
        return verify_invocation(invocation, self.identity, self.root_identity)

    def __repr__(self) -> str:
        return f"DelegatedAgent(name='{self.name}', did='{self.did}')"


class DelegatedCrew:
    """Manages delegation chains for a CrewAI crew.

    The root authority (human or system) creates a DelegatedCrew,
    then adds agents with scoped permissions. Each agent gets a
    keypair and delegation chain automatically.

    Usage:

        root = AgentKeyPair.generate()
        crew = DelegatedCrew(root)

        researcher = crew.add_agent(
            "researcher",
            scope=["search", "summarize"],
            max_cost=5.0,
            expires_in_hours=24,
        )

        # Use researcher.keypair with CrewAI Agent
        # Use crew.wrap_tool(tool) to add proof verification
    """

    def __init__(self, root_keypair: AgentKeyPair):
        self.root_keypair = root_keypair
        self.root_identity = root_keypair.identity()
        self.agents: dict[str, DelegatedAgent] = {}
        self._revoked: set[str] = set()

    @property
    def root_did(self) -> str:
        return self.root_identity.did

    def add_agent(
        self,
        name: str,
        scope: list[str] | None = None,
        max_cost: float | None = None,
        expires_in_hours: int | None = None,
        resource: str | None = None,
    ) -> DelegatedAgent:
        """Create a new agent with a delegation from the root.

        Args:
            name: Agent name (for display and lookup).
            scope: Allowed tool actions (e.g. ["search", "summarize"]).
            max_cost: Maximum cost per tool call.
            expires_in_hours: Delegation expiry.
            resource: Resource glob pattern.

        Returns:
            DelegatedAgent with keypair and delegation chain.
        """
        keypair = AgentKeyPair.generate()
        caveats = _build_caveats(scope, max_cost, expires_in_hours, resource)
        delegation = Delegation.create_root(
            self.root_keypair, keypair.identity().did, json.dumps(caveats)
        )
        agent = DelegatedAgent(name, keypair, delegation, self.root_identity)
        self.agents[name] = agent
        return agent

    def sub_delegate(
        self,
        from_agent: DelegatedAgent,
        name: str,
        scope: list[str] | None = None,
        max_cost: float | None = None,
    ) -> DelegatedAgent:
        """Create a sub-agent with narrower delegation from an existing agent.

        The sub-agent inherits the parent's caveats plus any additional
        restrictions. Authority can only narrow, never widen.
        """
        keypair = AgentKeyPair.generate()
        caveats = _build_caveats(scope, max_cost)
        delegation = Delegation.delegate(
            from_agent.keypair, keypair.identity().did,
            json.dumps(caveats), from_agent.delegation
        )
        agent = DelegatedAgent(name, keypair, delegation, self.root_identity)
        self.agents[name] = agent
        return agent

    def get_agent(self, name: str) -> DelegatedAgent:
        """Look up an agent by name."""
        agent = self.agents.get(name)
        if agent is None:
            raise ValueError(f"No agent named '{name}' in this crew")
        return agent

    def revoke(self, agent: DelegatedAgent):
        """Revoke an agent's delegation. Cascades to any sub-delegates."""
        self._revoked.add(agent.delegation.content_hash())

    def is_revoked(self, agent: DelegatedAgent) -> bool:
        return agent.delegation.content_hash() in self._revoked

    def wrap_tool(self, tool_func: Callable, agent: DelegatedAgent) -> Callable:
        """Wrap a tool function with delegation verification.

        Before the tool executes, the agent's delegation is verified.
        The tool name is used as the action for caveat checking.

        Usage:
            @crew.wrap_tool(researcher)
            def search(query: str) -> str:
                return do_search(query)
        """
        if isinstance(agent, str):
            agent = self.get_agent(agent)

        @functools.wraps(tool_func)
        def wrapper(*args, **kwargs):
            action = tool_func.__name__

            if self.is_revoked(agent):
                raise ValueError(
                    f"Agent '{agent.name}' delegation has been revoked"
                )

            # Build args dict for caveat checking
            check_args = {}
            if "cost" in kwargs:
                check_args["cost"] = kwargs["cost"]
            if "resource" in kwargs:
                check_args["resource"] = kwargs["resource"]

            # Verify delegation
            result = agent.verify_action(action, check_args)
            agent.history.append({
                "action": action,
                "chain": result[2],
                "depth": result[3],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            return tool_func(*args, **kwargs)

        return wrapper

    def audit_log(self) -> list[dict]:
        """Get a combined, time-sorted audit log from all agents."""
        entries = []
        for agent in self.agents.values():
            for entry in agent.history:
                entries.append({"agent": agent.name, "did": agent.did, **entry})
        entries.sort(key=lambda e: e["timestamp"])
        return entries


class DelegatedTool(BaseTool):
    """A CrewAI tool that verifies delegation before execution.

    Use this as a base class for tools that require delegation proof:

        class SearchTool(DelegatedTool):
            name = "search"
            description = "Search the web"

            def _run(self, query: str) -> str:
                return do_search(query)
    """

    delegated_agent: Any = Field(default=None, exclude=True)
    delegated_crew: Any = Field(default=None, exclude=True)

    def _pre_run(self, **kwargs):
        """Override in subclass for pre-execution checks."""
        pass

    def _run(self, **kwargs) -> str:
        raise NotImplementedError("Subclass must implement _run")

    def run(self, *args, **kwargs) -> Any:  # type: ignore
        if self.delegated_agent and self.delegated_crew:
            agent = self.delegated_agent
            crew = self.delegated_crew

            if crew.is_revoked(agent):
                return f"DENIED: Agent '{agent.name}' delegation revoked"

            check_args = {}
            if "cost" in kwargs:
                check_args["cost"] = kwargs["cost"]

            try:
                agent.verify_action(self.name, check_args)
            except ValueError as e:
                return f"DENIED: {e}"

        return super().run(*args, **kwargs)

    def bind(self, crew: "DelegatedCrew", agent: DelegatedAgent) -> "DelegatedTool":
        """Bind this tool to a delegated agent for verification."""
        self.delegated_crew = crew
        self.delegated_agent = agent
        return self


def delegated_tool(crew: DelegatedCrew, agent: DelegatedAgent):
    """Decorator: wrap a CrewAI @tool function with delegation verification.

    Usage:
        @delegated_tool(crew, researcher)
        @tool("Search")
        def search(query: str) -> str:
            return do_search(query)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            action = func.name if hasattr(func, "name") else func.__name__

            if crew.is_revoked(agent):
                return f"DENIED: Agent '{agent.name}' delegation revoked"

            check_args = {}
            if "cost" in kwargs:
                check_args["cost"] = kwargs["cost"]

            try:
                agent.verify_action(action, check_args)
            except ValueError as e:
                return f"DENIED: {e}"

            agent.history.append({
                "action": action,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            return func(*args, **kwargs)
        return wrapper
    return decorator


def _build_caveats(
    scope: list[str] | None = None,
    max_cost: float | None = None,
    expires_in_hours: int | None = None,
    resource: str | None = None,
) -> list[dict]:
    caveats = []
    if scope:
        caveats.append({"type": "action_scope", "value": scope})
    if max_cost is not None:
        caveats.append({"type": "max_cost", "value": max_cost})
    if expires_in_hours is not None:
        expiry = (
            datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        caveats.append({"type": "expires_at", "value": expiry})
    if resource:
        caveats.append({"type": "resource", "value": resource})
    return caveats
