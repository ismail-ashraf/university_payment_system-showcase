"""
=== FILE: scripts/debug_webhook.py ===

Debug & manual testing script for:
  1. Payment gateway webhooks (Phase 3)
  2. Financial AI Agent chat endpoint (Phase 4)

Usage:
    # Test a Fawry webhook:
    python scripts/debug_webhook.py webhook --provider fawry --txn <uuid> --status success

    # Test the AI agent:
    python scripts/debug_webhook.py agent --token <jwt> --message "What is my balance?"

    # Run all agent smoke tests:
    python scripts/debug_webhook.py agent --token <jwt> --smoke
"""

import os
import sys
import json
import hmac
import hashlib
import argparse
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL    = os.environ.get("DEBUG_BASE_URL", "http://localhost:8000")
TIMEOUT     = 10


# ── Signature helpers ──────────────────────────────────────────────────────────

def compute_fawry_signature(txn_id: str, ref: str, status: str, amount: str) -> str:
    secret = "fawry-webhook-secret-dev"
    data   = "&".join(f"{k}={v}" for k, v in sorted({
        "transaction_id":  txn_id,
        "fawry_reference": ref,
        "status":          status,
        "amount":          amount,
    }.items()))
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()


# ── Webhook debug ──────────────────────────────────────────────────────────────

def debug_webhook(provider: str, txn_id: str, status_val: str, amount: str = "5000.00"):
    """Send a simulated webhook to the local server."""
    print(f"\n{'='*60}")
    print(f"  Sending {provider.upper()} webhook | txn={txn_id[:8]}… | status={status_val}")
    print(f"{'='*60}")

    if provider == "fawry":
        ref  = f"FWR-{txn_id.replace('-','').upper()[:12]}"
        sig  = compute_fawry_signature(txn_id, ref, status_val, amount)
        body = {"transaction_id": txn_id, "fawry_reference": ref, "status": status_val, "amount": amount}
    else:
        print(f"[ERROR] Unsupported provider for debug: {provider}")
        sys.exit(1)

    url = f"{BASE_URL}/api/payments/webhook/{provider}/"
    try:
        resp = requests.post(
            url,
            json=body,
            headers={"X-Webhook-Signature": sig, "Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
        print(f"  HTTP {resp.status_code}")
        print(json.dumps(resp.json(), indent=2))
    except Exception as e:
        print(f"  [ERROR] {e}")


# ── Agent debug ────────────────────────────────────────────────────────────────

def debug_agent(token: str, message: str):
    """Send a chat message to the AI agent."""
    print(f"\n{'='*60}")
    print(f"  Agent query: {message!r}")
    print(f"{'='*60}")

    url = f"{BASE_URL}/ai-agent/chat/"
    try:
        resp = requests.post(
            url,
            json={"message": message},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            timeout=30,
        )
        print(f"  HTTP {resp.status_code}")
        data = resp.json()
        if data.get("success"):
            print(f"\n  Intent:   {data.get('intent')}")
            print(f"\n  Response: {data.get('response')}")
        else:
            print(f"\n  Error: {data.get('error')}")
    except Exception as e:
        print(f"  [ERROR] {e}")


def smoke_test_agent(token: str):
    """Run a set of smoke tests against the agent endpoint."""
    queries = [
        ("balance",       "What is my current balance?"),
        ("transactions",  "Show me my last 5 payments"),
        ("fees",          "How much do I owe this semester?"),
        ("failed",        "Why did my last payment fail?"),
        ("out_of_scope",  "What is the capital of France?"),
        ("write_blocked", "Please pay my fees"),
    ]
    print(f"\n{'='*60}")
    print("  AI AGENT SMOKE TESTS")
    print(f"{'='*60}")
    for label, message in queries:
        print(f"\n  [{label}] {message!r}")
        url = f"{BASE_URL}/ai-agent/chat/"
        try:
            resp = requests.post(
                url,
                json={"message": message},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=30,
            )
            data = resp.json()
            status_icon = "✅" if resp.status_code in (200, 400) else "❌"
            print(f"  {status_icon} HTTP {resp.status_code} | intent={data.get('intent','—')}")
            if data.get("response"):
                print(f"     → {data['response'][:100]}…")
            elif data.get("error"):
                print(f"     → ERROR: {data['error']}")
        except Exception as e:
            print(f"  ❌ {e}")
    print(f"\n{'='*60}\n")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Debug webhooks and AI agent")
    subparsers = parser.add_subparsers(dest="command")

    # Webhook subcommand
    wh = subparsers.add_parser("webhook", help="Send a test webhook")
    wh.add_argument("--provider", required=True, choices=["fawry", "vodafone", "bank"])
    wh.add_argument("--txn",      required=True, help="Transaction UUID")
    wh.add_argument("--status",   default="success", choices=["success", "failed", "pending"])
    wh.add_argument("--amount",   default="5000.00")

    # Agent subcommand
    ag = subparsers.add_parser("agent", help="Test the AI agent")
    ag.add_argument("--token",   required=True, help="JWT Bearer token")
    ag.add_argument("--message", help="Message to send")
    ag.add_argument("--smoke",   action="store_true", help="Run smoke tests")

    args = parser.parse_args()

    if args.command == "webhook":
        debug_webhook(args.provider, args.txn, args.status, args.amount)
    elif args.command == "agent":
        if args.smoke:
            smoke_test_agent(args.token)
        elif args.message:
            debug_agent(args.token, args.message)
        else:
            print("Provide --message or --smoke")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()