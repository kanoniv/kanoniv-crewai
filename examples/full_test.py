#!/usr/bin/env python3
"""
Full integration test for kanoniv-crewai.

Tests every function and edge case. Run this to find bugs.

    python examples/full_test.py
"""

import json
import sys
from kanoniv_agent_auth import AgentKeyPair, McpProof
from kanoniv_crewai import DelegatedCrew, DelegatedAgent, delegated_tool


passed = 0
failed = 0


def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  \033[32mPASS\033[0m {name}")
        passed += 1
    except Exception as e:
        print(f"  \033[31mFAIL\033[0m {name}: {e}")
        failed += 1


def expect_denied(fn):
    """Helper: expects fn() to raise ValueError."""
    try:
        fn()
        raise AssertionError("Expected ValueError but got success")
    except ValueError:
        pass  # expected


def main():
    global passed, failed

    print("\n\033[1m=== DelegatedCrew Tests ===\033[0m\n")

    root = AgentKeyPair.generate()
    crew = DelegatedCrew(root)

    # ── Basic setup ──────────────────────────────────────────

    print("\033[33mSetup\033[0m")

    def test_root_did():
        assert crew.root_did.startswith("did:agent:")
        assert len(crew.root_did) == 42  # did:agent: + 32 hex chars
    test("root DID format", test_root_did)

    agent_a = crew.add_agent("agent_a", scope=["search", "write"], max_cost=10.0, expires_in_hours=24)
    agent_b = crew.add_agent("agent_b", scope=["search"], max_cost=5.0)

    def test_agent_did():
        assert agent_a.did.startswith("did:agent:")
        assert agent_a.did != agent_b.did
    test("agent DIDs are unique", test_agent_did)

    def test_agent_name():
        assert agent_a.name == "agent_a"
        assert agent_b.name == "agent_b"
    test("agent names", test_agent_name)

    def test_agent_identity():
        identity = agent_a.identity
        assert identity.did == agent_a.did
        assert len(identity.public_key_bytes) == 32
    test("agent identity", test_agent_identity)

    def test_get_agent():
        assert crew.get_agent("agent_a").did == agent_a.did
    test("get_agent by name", test_get_agent)

    def test_get_agent_missing():
        expect_denied(lambda: crew.get_agent("nonexistent"))
    test("get_agent missing raises", test_get_agent_missing)

    def test_repr():
        r = repr(agent_a)
        assert "DelegatedAgent" in r
        assert "agent_a" in r
    test("agent repr", test_repr)

    # ── Verify action ────────────────────────────────────────

    print("\n\033[33mVerify Action\033[0m")

    def test_verify_allowed():
        result = agent_a.verify_action("search", {"cost": 1.0})
        invoker_did, root_did, chain, depth = result
        assert invoker_did == agent_a.did
        assert root_did == crew.root_did
        assert depth >= 1
        assert len(chain) >= 2
    test("verify allowed action", test_verify_allowed)

    def test_verify_write():
        result = agent_a.verify_action("write", {"cost": 2.0})
        assert result[0] == agent_a.did
    test("verify write (in scope)", test_verify_write)

    def test_verify_wrong_action():
        expect_denied(lambda: agent_a.verify_action("delete", {"cost": 1.0}))
    test("deny action not in scope", test_verify_wrong_action)

    def test_verify_over_cost():
        expect_denied(lambda: agent_a.verify_action("search", {"cost": 15.0}))
    test("deny over cost cap", test_verify_over_cost)

    def test_verify_exact_cost():
        result = agent_a.verify_action("search", {"cost": 10.0})
        assert result[0] == agent_a.did
    test("allow exact cost cap", test_verify_exact_cost)

    def test_verify_zero_cost():
        result = agent_b.verify_action("search", {"cost": 0.0})
        assert result[0] == agent_b.did
    test("allow zero cost", test_verify_zero_cost)

    def test_verify_no_cost_with_cap():
        # max_cost caveat requires cost field in args
        expect_denied(lambda: agent_a.verify_action("search", {}))
    test("deny missing cost when cap exists", test_verify_no_cost_with_cap)

    def test_agent_b_no_write():
        expect_denied(lambda: agent_b.verify_action("write", {"cost": 1.0}))
    test("agent_b denied write (not in scope)", test_agent_b_no_write)

    # ── Sub-delegation ───────────────────────────────────────

    print("\n\033[33mSub-delegation\033[0m")

    sub_agent = crew.sub_delegate(agent_a, "sub_agent", scope=["search"], max_cost=3.0)

    def test_sub_did():
        assert sub_agent.did.startswith("did:agent:")
        assert sub_agent.did != agent_a.did
    test("sub-agent has unique DID", test_sub_did)

    def test_sub_allowed():
        result = sub_agent.verify_action("search", {"cost": 2.0})
        assert result[3] == 2  # depth: sub -> agent_a -> root
    test("sub-agent search allowed (depth 2)", test_sub_allowed)

    def test_sub_narrowed_scope():
        expect_denied(lambda: sub_agent.verify_action("write", {"cost": 1.0}))
    test("sub-agent denied write (narrowed scope)", test_sub_narrowed_scope)

    def test_sub_narrowed_cost():
        expect_denied(lambda: sub_agent.verify_action("search", {"cost": 5.0}))
    test("sub-agent denied over $3 (narrowed cost)", test_sub_narrowed_cost)

    def test_sub_exact_cost():
        result = sub_agent.verify_action("search", {"cost": 3.0})
        assert result[0] == sub_agent.did
    test("sub-agent exact $3 allowed", test_sub_exact_cost)

    # ── Deep chain (3 levels) ────────────────────────────────

    print("\n\033[33mDeep Chain\033[0m")

    deep_agent = crew.sub_delegate(sub_agent, "deep_agent", scope=["search"], max_cost=1.0)

    def test_deep_depth():
        result = deep_agent.verify_action("search", {"cost": 0.5})
        assert result[3] == 3  # deep -> sub -> agent_a -> root
    test("deep chain depth 3", test_deep_depth)

    def test_deep_narrowed():
        expect_denied(lambda: deep_agent.verify_action("search", {"cost": 2.0}))
    test("deep agent denied over $1 (double narrowed)", test_deep_narrowed)

    # ── MCP Proof creation ───────────────────────────────────

    print("\n\033[33mMCP Proofs\033[0m")

    def test_create_proof():
        proof = agent_a.create_proof("search", {"cost": 1.0})
        assert proof.invoker_public_key is not None
        assert len(proof.invoker_public_key) == 64
        assert proof.invoker_did == agent_a.did
        assert proof.action == "search"
    test("create MCP proof", test_create_proof)

    def test_proof_json_roundtrip():
        proof = agent_a.create_proof("search", {"cost": 1.0})
        json_str = proof.to_json()
        parsed = json.loads(json_str)
        assert parsed["invoker_public_key"] == proof.invoker_public_key
        restored = McpProof.from_json(json_str)
        assert restored.invoker_did == agent_a.did
    test("proof JSON roundtrip", test_proof_json_roundtrip)

    def test_proof_wrong_action():
        # Proof creation succeeds but verification would fail
        proof = agent_a.create_proof("delete", {"cost": 1.0})
        # We can create it, but verify_mcp_call with root identity would fail on caveats
        assert proof.action == "delete"
    test("proof creation does not check caveats", test_proof_wrong_action)

    # ── Revocation ───────────────────────────────────────────

    print("\n\033[33mRevocation\033[0m")

    revoke_agent = crew.add_agent("to_revoke", scope=["search"], max_cost=5.0)

    def test_not_revoked():
        assert not crew.is_revoked(revoke_agent)
    test("agent not revoked initially", test_not_revoked)

    def test_verify_before_revoke():
        result = revoke_agent.verify_action("search", {"cost": 1.0})
        assert result[0] == revoke_agent.did
    test("verify succeeds before revocation", test_verify_before_revoke)

    crew.revoke(revoke_agent)

    def test_is_revoked():
        assert crew.is_revoked(revoke_agent)
    test("is_revoked returns True", test_is_revoked)

    def test_verify_after_revoke():
        expect_denied(lambda: revoke_agent.verify_action("search", {"cost": 1.0}))
    test("verify denied after revocation", test_verify_after_revoke)

    def test_other_agents_unaffected():
        result = agent_a.verify_action("search", {"cost": 1.0})
        assert result[0] == agent_a.did
    test("other agents unaffected by revocation", test_other_agents_unaffected)

    # ── Cascade revocation (revoke parent) ───────────────────

    print("\n\033[33mCascade Revocation\033[0m")

    parent = crew.add_agent("parent", scope=["search", "write"], max_cost=10.0)
    child = crew.sub_delegate(parent, "child", scope=["search"], max_cost=5.0)

    def test_child_works():
        result = child.verify_action("search", {"cost": 1.0})
        assert result[3] == 2
    test("child works before parent revoked", test_child_works)

    crew.revoke(parent)

    def test_parent_revoked():
        expect_denied(lambda: parent.verify_action("search", {"cost": 1.0}))
    test("parent denied after revocation", test_parent_revoked)

    # Note: child's delegation is from parent, but revocation is checked by hash
    # on the agent's own delegation, not the parent's. This is a design choice.
    def test_child_after_parent_revoked():
        # Child has its own delegation hash, separate from parent's
        # To cascade, you'd need to revoke child explicitly too
        result = child.verify_action("search", {"cost": 1.0})
        assert result[0] == child.did
    test("child still works (revocation is per-agent, not cascading)", test_child_after_parent_revoked)

    # ── History / Audit ──────────────────────────────────────

    print("\n\033[33mHistory and Audit\033[0m")

    def test_agent_history():
        assert len(agent_a.history) > 0
        entry = agent_a.history[0]
        assert "action" in entry
        assert "chain" in entry
        assert "depth" in entry
        assert "timestamp" in entry
    test("agent has history entries", test_agent_history)

    def test_audit_log():
        log = crew.audit_log()
        assert len(log) > 0
        entry = log[0]
        assert "agent" in entry
        assert "did" in entry
        assert "action" in entry
    test("crew audit log has entries", test_audit_log)

    def test_audit_sorted():
        log = crew.audit_log()
        timestamps = [e["timestamp"] for e in log]
        assert timestamps == sorted(timestamps)
    test("audit log is time-sorted", test_audit_sorted)

    def test_denied_not_in_history():
        # Count history before a denied action
        count_before = len(agent_b.history)
        try:
            agent_b.verify_action("write", {"cost": 1.0})
        except ValueError:
            pass
        count_after = len(agent_b.history)
        assert count_after == count_before
    test("denied actions not logged in history", test_denied_not_in_history)

    # ── wrap_tool ────────────────────────────────────────────

    print("\n\033[33mwrap_tool\033[0m")

    wrap_agent = crew.add_agent("wrapper", scope=["greet"], max_cost=1.0)

    def greet(name: str, cost: float = 0) -> str:
        return f"Hello, {name}!"

    wrapped = crew.wrap_tool(greet, wrap_agent)

    def test_wrap_allowed():
        result = wrapped("Alice", cost=0.5)
        assert result == "Hello, Alice!"
    test("wrapped tool executes on allowed action", test_wrap_allowed)

    def test_wrap_denied_cost():
        try:
            wrapped("Bob", cost=5.0)
            raise AssertionError("Expected ValueError")
        except ValueError as e:
            assert "cost" in str(e).lower()
    test("wrapped tool denied over cost", test_wrap_denied_cost)

    crew.revoke(wrap_agent)

    def test_wrap_denied_revoked():
        try:
            wrapped("Charlie", cost=0.1)
            raise AssertionError("Expected ValueError")
        except ValueError as e:
            assert "revoked" in str(e).lower()
    test("wrapped tool denied after revocation", test_wrap_denied_revoked)

    # ── delegated_tool decorator ─────────────────────────────

    print("\n\033[33m@delegated_tool\033[0m")

    dt_agent = crew.add_agent("dt_agent", scope=["add"], max_cost=1.0)

    @delegated_tool(crew, dt_agent)
    def add(a: int, b: int, cost: float = 0) -> str:
        return str(a + b)

    def test_delegated_tool_allowed():
        result = add(2, 3, cost=0.1)
        assert result == "5"
    test("@delegated_tool allowed", test_delegated_tool_allowed)

    def test_delegated_tool_denied():
        result = add(2, 3, cost=5.0)
        assert "DENIED" in str(result)
    test("@delegated_tool denied over cost", test_delegated_tool_denied)

    crew.revoke(dt_agent)

    def test_delegated_tool_revoked():
        result = add(2, 3, cost=0.1)
        assert "DENIED" in str(result)
    test("@delegated_tool denied after revocation", test_delegated_tool_revoked)

    # ── Edge cases ───────────────────────────────────────────

    print("\n\033[33mEdge Cases\033[0m")

    def test_empty_scope():
        empty = crew.add_agent("empty", scope=[], max_cost=5.0)
        # Empty scope means no action_scope caveat - all actions allowed
        result = empty.verify_action("anything", {"cost": 1.0})
        assert result[0] == empty.did
    test("empty scope list (no restriction)", test_empty_scope)

    def test_no_scope():
        no_scope = crew.add_agent("no_scope", max_cost=5.0)
        result = no_scope.verify_action("anything", {"cost": 1.0})
        assert result[0] == no_scope.did
    test("no scope param (no restriction)", test_no_scope)

    def test_no_cost():
        no_cost = crew.add_agent("no_cost", scope=["search"])
        result = no_cost.verify_action("search")
        assert result[0] == no_cost.did
    test("no max_cost (no cost restriction)", test_no_cost)

    def test_negative_cost():
        neg = crew.add_agent("neg", scope=["search"], max_cost=5.0)
        result = neg.verify_action("search", {"cost": -1.0})
        assert result[0] == neg.did
    test("negative cost (passes - under cap)", test_negative_cost)

    # ── Summary ──────────────────────────────────────────────

    print(f"\n\033[1m{'=' * 50}\033[0m")
    print(f"\033[1m  {passed + failed} tests: \033[32m{passed} passed\033[0m, \033[31m{failed} failed\033[0m")
    print(f"\033[1m{'=' * 50}\033[0m\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
