"""
kanoniv-crewai demo: delegation chain with verification.

Run: python examples/demo.py

Shows:
1. Root delegates to researcher (search only, max $5)
2. Researcher delegates to helper (search only, max $2)
3. Allowed action: search
4. Blocked: helper tries to write (not in scope)
5. Blocked: helper tries expensive search (over $2 cap)
6. Revocation: researcher revoked, all tool calls fail
"""

from kanoniv_agent_auth import AgentKeyPair
from kanoniv_crewai import DelegatedCrew


def main():
    print("=== kanoniv-crewai Demo ===\n")

    # Root authority
    root = AgentKeyPair.generate()
    crew = DelegatedCrew(root)
    print(f"Root DID: {crew.root_did}")

    # Add agents
    researcher = crew.add_agent(
        "researcher",
        scope=["search", "summarize"],
        max_cost=5.0,
        expires_in_hours=24,
    )
    print(f"Researcher DID: {researcher.did}")

    # Sub-delegate to helper (narrower scope)
    helper = crew.sub_delegate(
        researcher,
        "helper",
        scope=["search"],
        max_cost=2.0,
    )
    print(f"Helper DID: {helper.did}")

    # --- Allowed action ---
    print("\n[1] Helper searches (allowed)...")
    result = helper.verify_action("search", {"cost": 0.50})
    print(f"    VERIFIED: chain depth {result[3]}, path: {' -> '.join(result[2])}")

    # --- Blocked: wrong action ---
    print("\n[2] Helper tries to summarize (not in scope)...")
    try:
        helper.verify_action("summarize", {"cost": 0.50})
        print("    ERROR: should have been blocked")
    except ValueError as e:
        print(f"    DENIED: {e}")

    # --- Blocked: over budget ---
    print("\n[3] Helper tries $3 search (over $2 cap)...")
    try:
        helper.verify_action("search", {"cost": 3.0})
        print("    ERROR: should have been blocked")
    except ValueError as e:
        print(f"    DENIED: {e}")

    # --- Researcher can still do more ---
    print("\n[4] Researcher summarizes (allowed - broader scope)...")
    result = researcher.verify_action("summarize", {"cost": 2.0})
    print(f"    VERIFIED: chain depth {result[3]}")

    # --- Revocation ---
    print("\n[5] Revoking researcher...")
    crew.revoke(researcher)
    print(f"    Researcher revoked: {crew.is_revoked(researcher)}")

    # --- Audit log ---
    print(f"\n[6] Audit log: {len(crew.audit_log())} entries")
    for entry in crew.audit_log():
        print(f"    {entry['agent']} ({entry['did'][:24]}...) -> {entry['action']}")

    print("\nDone.")


if __name__ == "__main__":
    main()
