"""Replay the demo call against a running API, printing what the agent would say and the tools it calls.

    uvicorn app.main:create_app --factory --port 8000      # in another terminal
    python scripts/demo_call.py [--base-url http://localhost:8000] [--pause 1.2]

Use it to rehearse, to check a deployment end-to-end, or as B-roll for the demo video.
"""
import argparse
import json
import os
import sys
import time
import uuid

import httpx

DIM, BOLD, CYAN, GREEN, YELLOW, RESET = "\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[0m"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.getenv("BASE_URL", "http://localhost:8000"))
    p.add_argument("--pause", type=float, default=0.8)
    args = p.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=10,
                          headers={"X-Tool-Secret": os.getenv("TOOL_SECRET", "dev-tool-secret")})
    convo = f"conv_demo_{uuid.uuid4().hex[:6]}"

    def say(who: str, text: str):
        color = CYAN if who == "Nova" else BOLD
        print(f"{color}{who:>6}:{RESET} {text}")
        time.sleep(args.pause)

    def tool(name: str, **body) -> dict:
        body["conversation_id"] = convo
        r = client.post(f"/tools/{name}", json=body)
        shown = {k: v for k, v in body.items() if k != "conversation_id"}
        status = GREEN if r.is_success else YELLOW
        print(f"{DIM}        → {name}({json.dumps(shown)}){RESET} {status}{r.status_code}{RESET}")
        return r.json()

    say("Caller", "Hi, I think I left my work laptop in a taxi.")
    say("Nova", "Okay, let's get that secured. What's your work email?")
    say("Caller", "priya dot shah at northwind dot example")
    found = tool("lookup_device", email="priya.shah@northwind.example")
    say("Nova", found["speakable"] + " Is it the MacBook?")
    say("Caller", "Yes, the MacBook.")
    device = found["data"]["devices"][0]

    ticket = tool("create_ticket", device_id=device["device_id"], caller_email="priya.shah@northwind.example",
                  summary="MacBook left in a taxi; caller requests remote lock.", category="lost_or_stolen")
    say("Nova", ticket["speakable"] + " I can remotely lock it so nobody can get in. Want me to do that?")
    say("Caller", "Please.")

    pending = tool("request_device_action", device_id=device["device_id"], action="lock",
                   ticket_id=ticket["data"]["id"], caller_email="priya.shah@northwind.example")
    say("Nova", pending["data"]["readback"])
    say("Caller", "Um, which one?")
    retry = tool("confirm_device_action", pending_action_id=pending["data"]["pending_action_id"],
                 caller_utterance="Um, which one?")
    say("Nova", retry["speakable"])
    say("Caller", "Yes, go ahead.")
    done = tool("confirm_device_action", pending_action_id=pending["data"]["pending_action_id"],
                caller_utterance="Yes, go ahead.")
    say("Nova", done["speakable"] + " Anything else?")
    say("Caller", "No, that's it. Thanks!")

    admin = {"X-Admin-Key": os.getenv("ADMIN_KEY", "dev-admin-key")}
    trail = client.get("/admin/audit", params={"conversation_id": convo}, headers=admin).json()["data"]
    print(f"\n{BOLD}Audit trail for {convo}{RESET}")
    for e in trail:
        extra = e["details"].get("utterance") or e["details"].get("mdm_command_id") or ""
        print(f"  {e['seq']:>4}  {e['ts'][11:23]}  {e['event']:<24} {e['target'] or '':<12} {DIM}{extra}{RESET}")
    check = client.get("/admin/audit/verify", headers=admin).json()["data"]
    mark = f"{GREEN}✔ hash chain valid" if check["valid"] else f"{YELLOW}✘ chain broken at {check['first_invalid_seq']}"
    print(f"\n  {mark}{RESET} ({check['entries_checked']} entries)")
    return 0 if done.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
