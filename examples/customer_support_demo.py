#!/usr/bin/env python3
"""
Customer Support Escalation Demo
=================================

Real-world scenario: A customer reports a duplicate charge.
Delegation chains control which agents can search, refund, or escalate
- and how much they can refund.

    Human (CEO)
      |
      +-- Support Manager: [search, refund, escalate], max $100
          |
          +-- L1 Bot: [search, refund], max $25
          |
          +-- L2 Agent: [search, refund, escalate], max $75

Run:
    cd kanoniv-crewai
    pip install kanoniv-agent-auth
    python examples/customer_support_demo.py
"""

import json
from datetime import datetime, timezone
from kanoniv_agent_auth import AgentKeyPair
from kanoniv_crewai import DelegatedCrew


# ── Mock tools (replace with real APIs) ──────────────────────────

ORDERS = {
    "ORD-4521": {
        "customer": "alice@example.com",
        "items": ["Wireless Headphones"],
        "charges": [
            {"amount": 29.99, "date": "2026-03-10", "status": "completed"},
            {"amount": 29.99, "date": "2026-03-10", "status": "completed"},  # duplicate!
        ],
        "total_charged": 59.98,
        "expected_total": 29.99,
    },
    "ORD-7832": {
        "customer": "bob@example.com",
        "items": ["USB-C Cable", "Phone Case"],
        "charges": [
            {"amount": 42.50, "date": "2026-03-12", "status": "completed"},
        ],
        "total_charged": 42.50,
        "expected_total": 42.50,
    },
}

REFUND_LOG = []


def search_order(order_id: str) -> dict:
    """Look up an order by ID."""
    order = ORDERS.get(order_id)
    if not order:
        return {"error": f"Order {order_id} not found"}
    overcharge = order["total_charged"] - order["expected_total"]
    return {
        "order_id": order_id,
        "customer": order["customer"],
        "items": order["items"],
        "total_charged": order["total_charged"],
        "expected_total": order["expected_total"],
        "overcharge": round(overcharge, 2),
        "duplicate_detected": overcharge > 0,
    }


def issue_refund(order_id: str, amount: float, agent_did: str) -> dict:
    """Process a refund."""
    entry = {
        "order_id": order_id,
        "amount": amount,
        "agent_did": agent_did,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "processed",
    }
    REFUND_LOG.append(entry)
    return entry


def escalate_to_engineering(order_id: str, reason: str, agent_did: str) -> dict:
    """Escalate an issue to the engineering team."""
    return {
        "order_id": order_id,
        "reason": reason,
        "escalated_by": agent_did,
        "ticket": "ENG-1042",
        "status": "created",
    }


# ── Colors for terminal output ───────────────────────────────────

GOLD = "\033[33m"
BLUE = "\033[34m"
GREEN = "\033[32m"
RED = "\033[31m"
CYAN = "\033[36m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def header(text):
    print(f"\n{BOLD}{GOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}{GOLD}  {text}{RESET}")
    print(f"{BOLD}{GOLD}{'=' * 60}{RESET}\n")


def step(num, text):
    print(f"{BOLD}{CYAN}[{num}]{RESET} {text}")


def verified(text):
    print(f"    {GREEN}VERIFIED{RESET} {text}")


def denied(text):
    print(f"    {RED}DENIED{RESET} {text}")


def info(text):
    print(f"    {DIM}{text}{RESET}")


def agent_label(name, did):
    return f"{BLUE}{name}{RESET} {DIM}({did[:24]}...){RESET}"


# ── Demo ─────────────────────────────────────────────────────────

def main():
    header("Customer Support Escalation Demo")
    print(f"{DIM}Scenario: Customer reports duplicate charge on order ORD-4521{RESET}")
    print(f"{DIM}Delegation enforces who can search, refund, and escalate.{RESET}\n")

    # ── Setup: create delegation chain ───────────────────────────

    step(1, "Setting up delegation chain\n")

    root = AgentKeyPair.generate()
    crew = DelegatedCrew(root)

    manager = crew.add_agent(
        "Support Manager",
        scope=["search", "refund", "escalate"],
        max_cost=100.0,
        expires_in_hours=8,  # shift-length delegation
    )

    l1_bot = crew.sub_delegate(
        manager,
        "L1 Bot",
        scope=["search", "refund"],  # no escalate
        max_cost=25.0,
    )

    l2_agent = crew.sub_delegate(
        manager,
        "L2 Agent",
        scope=["search", "refund", "escalate"],
        max_cost=75.0,
    )

    print(f"    Root (CEO):       {DIM}{crew.root_did}{RESET}")
    print(f"    Support Manager:  {DIM}{manager.did}{RESET}")
    print(f"    L1 Bot:           {DIM}{l1_bot.did}{RESET}")
    print(f"    L2 Agent:         {DIM}{l2_agent.did}{RESET}")
    print()
    print(f"    {GOLD}Delegation chain:{RESET}")
    print(f"    CEO -> Manager: [search, refund, escalate], max $100")
    print(f"    Manager -> L1:  [search, refund], max $25")
    print(f"    Manager -> L2:  [search, refund, escalate], max $75")

    # ── Act 1: L1 Bot investigates ───────────────────────────────

    header("Act 1: L1 Bot Investigates")

    step(2, f"{agent_label('L1 Bot', l1_bot.did)} searches for order ORD-4521")

    try:
        result = l1_bot.verify_action("search", {"cost": 0.10})
        verified(f"chain depth {result[3]}")
        order = search_order("ORD-4521")
        info(f"Customer: {order['customer']}")
        info(f"Charged: ${order['total_charged']} (expected: ${order['expected_total']})")
        info(f"Overcharge: ${order['overcharge']}")
        info(f"Duplicate detected: {order['duplicate_detected']}")
    except ValueError as e:
        denied(str(e))

    print()
    step(3, f"{agent_label('L1 Bot', l1_bot.did)} tries to refund ${order['overcharge']}")

    try:
        l1_bot.verify_action("refund", {"cost": order["overcharge"]})
        verified("refund authorized")
    except ValueError as e:
        denied(str(e))
        info(f"L1 Bot cap is $25, refund amount is ${order['overcharge']}")

    print()
    step(4, f"{agent_label('L1 Bot', l1_bot.did)} tries to escalate to engineering")

    try:
        l1_bot.verify_action("escalate", {"cost": 0})
        verified("escalation authorized")
    except ValueError as e:
        denied(str(e))
        info("L1 Bot does not have 'escalate' in its scope")

    # ── Act 2: L2 Agent takes over ───────────────────────────────

    header("Act 2: L2 Agent Takes Over")

    step(5, f"{agent_label('L2 Agent', l2_agent.did)} searches the same order")

    try:
        result = l2_agent.verify_action("search", {"cost": 0.10})
        verified(f"chain depth {result[3]}")
        order = search_order("ORD-4521")
        info(f"Same result: ${order['overcharge']} overcharge")
    except ValueError as e:
        denied(str(e))

    print()
    step(6, f"{agent_label('L2 Agent', l2_agent.did)} refunds ${order['overcharge']}")

    try:
        result = l2_agent.verify_action("refund", {"cost": order["overcharge"]})
        verified(f"chain depth {result[3]}, path: {' -> '.join(result[2])}")
        refund = issue_refund("ORD-4521", order["overcharge"], l2_agent.did)
        info(f"Refund processed: ${refund['amount']} to {order['customer']}")
    except ValueError as e:
        denied(str(e))

    # ── Act 3: Edge cases ────────────────────────────────────────

    header("Act 3: Edge Cases")

    step(7, f"{agent_label('L2 Agent', l2_agent.did)} tries $80 refund (over $75 cap)")

    try:
        l2_agent.verify_action("refund", {"cost": 80.0})
        verified("should not happen")
    except ValueError as e:
        denied(str(e))
        info("L2 Agent cap is $75")

    print()
    step(8, f"CEO revokes L2 Agent's delegation")

    crew.revoke(l2_agent)
    info(f"L2 Agent revoked: {crew.is_revoked(l2_agent)}")

    print()
    step(9, f"{agent_label('L2 Agent', l2_agent.did)} tries to search after revocation")

    try:
        l2_agent.verify_action("search", {"cost": 0.10})
        verified("should not happen")
    except ValueError as e:
        denied(str(e))
        info("Revoked agents cannot perform any action")

    # ── Audit trail ──────────────────────────────────────────────

    header("Audit Trail")

    log = crew.audit_log()
    print(f"    {BOLD}{len(log)} verified actions{RESET} (denied actions are not logged)\n")

    for entry in log:
        did_short = entry["did"][:20]
        print(f"    {DIM}{entry['timestamp'][:19]}{RESET}  "
              f"{BLUE}{entry['agent']:16s}{RESET}  "
              f"{entry['action']:10s}  "
              f"{DIM}depth={entry['depth']}{RESET}")

    if REFUND_LOG:
        print(f"\n    {BOLD}Refunds processed:{RESET}")
        for r in REFUND_LOG:
            print(f"    {GREEN}${r['amount']}{RESET} on {r['order_id']} "
                  f"by {DIM}{r['agent_did'][:24]}...{RESET}")

    # ── Summary ──────────────────────────────────────────────────

    header("Summary")

    print(f"    {GREEN}3 actions verified{RESET} (L1 search, L2 search, L2 refund)")
    print(f"    {RED}4 actions denied{RESET} (L1 refund over cap, L1 escalate, L2 over cap, L2 revoked)")
    print(f"    {GOLD}1 refund processed{RESET} (${order['overcharge']} by L2 Agent)")
    print(f"    {CYAN}Full cryptographic audit trail{RESET} with Ed25519 signatures")
    print()
    print(f"    Every action was verified against the delegation chain.")
    print(f"    No agent exceeded its authority. No unauthorized refunds.")
    print(f"    The CEO can see exactly who did what and when.")
    print()


if __name__ == "__main__":
    main()
