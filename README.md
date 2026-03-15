# kanoniv-crewai

Cryptographic identity and delegation for CrewAI agents.

Every agent gets a `did:agent:` DID. Every tool call carries a delegation proof. Authority flows from human to crew to agent, narrowing at each step.

## Install

```bash
pip install kanoniv-crewai
```

## Quick Start

```python
from kanoniv_agent_auth import AgentKeyPair
from kanoniv_crewai import DelegatedCrew, delegated_tool
from crewai import Agent, Task, Crew, tool

# Root authority (human or system)
root = AgentKeyPair.generate()
crew = DelegatedCrew(root)

# Add agents with scoped permissions
researcher = crew.add_agent("researcher", scope=["search"], max_cost=5.0, expires_in_hours=24)
writer = crew.add_agent("writer", scope=["write"], max_cost=3.0)

print(f"Root:       {crew.root_did}")
print(f"Researcher: {researcher.did}")
print(f"Writer:     {writer.did}")

# Wrap tools with delegation verification
@delegated_tool(crew, researcher)
@tool("search")
def search(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"

@delegated_tool(crew, writer)
@tool("write")
def write(content: str) -> str:
    """Write content to a document."""
    return f"Wrote: {content}"

# Create CrewAI agents with delegated tools
research_agent = Agent(
    role="Research Analyst",
    goal="Find accurate information",
    backstory="You are a thorough researcher.",
    tools=[search],
)

writing_agent = Agent(
    role="Content Writer",
    goal="Write clear, concise content",
    backstory="You are an experienced writer.",
    tools=[write],
)

# Every tool call is verified against the delegation chain
```

## Sub-Delegation

Agents can delegate to sub-agents with narrower scope:

```python
# Researcher delegates to a specialized searcher
searcher = crew.sub_delegate(
    researcher,
    "searcher",
    scope=["search"],
    max_cost=2.0,  # narrower than researcher's $5
)

# searcher can only search, max $2 per call
# researcher can search at max $5
# writer can only write at max $3
```

## Revocation

```python
# Revoke an agent's delegation
crew.revoke(writer)

# All subsequent tool calls by writer will fail:
# "DENIED: Agent 'writer' delegation has been revoked"
```

## Audit Trail

```python
# Get time-sorted audit log from all agents
for entry in crew.audit_log():
    print(f"{entry['timestamp']} {entry['agent']} ({entry['did'][:20]}...) {entry['action']}")
```

## How It Works

1. `DelegatedCrew(root_keypair)` creates a root authority
2. `crew.add_agent(name, scope, max_cost)` generates a keypair and delegation for each agent
3. `@delegated_tool(crew, agent)` wraps tool functions with verification
4. Before each tool call, the delegation chain is verified:
   - Is the delegation still valid (not expired, not revoked)?
   - Is the action in the agent's scope?
   - Is the cost within limits?
5. If verification fails, the tool returns a DENIED message
6. If verification passes, the tool executes normally

The delegation chain is cryptographic (Ed25519 signatures). It cannot be forged, tampered with, or escalated. Caveats can only narrow, never widen.

## API

### DelegatedCrew

| Method | Description |
|--------|-------------|
| `add_agent(name, scope, max_cost, expires_in_hours, resource)` | Create an agent with delegation from root |
| `sub_delegate(from_agent, name, scope, max_cost)` | Create a sub-agent with narrower delegation |
| `get_agent(name)` | Look up agent by name |
| `revoke(agent)` | Revoke an agent's delegation |
| `is_revoked(agent)` | Check if delegation is revoked |
| `wrap_tool(tool_func, agent)` | Wrap a function with delegation verification |
| `audit_log()` | Get combined audit log from all agents |

### DelegatedAgent

| Property/Method | Description |
|----------------|-------------|
| `did` | The agent's `did:agent:` DID |
| `identity` | The agent's `AgentIdentity` |
| `keypair` | The agent's `AgentKeyPair` |
| `create_proof(action, args)` | Create an MCP proof for a tool call |
| `verify_action(action, args)` | Verify delegation allows this action |
| `history` | List of verified actions |

## Links

- [kanoniv-agent-auth](https://github.com/kanoniv/agent-auth) - The core identity and delegation library
- [CrewAI](https://crewai.com) - Multi-agent orchestration framework
- [MCP Auth Proposal](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/2404) - Adding agent delegation to the MCP spec

## License

MIT
