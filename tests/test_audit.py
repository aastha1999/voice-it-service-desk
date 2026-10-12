import sqlite3

import pytest

from tests.conftest import CONVO


def _full_flow(h):
    h.tool("lookup_device", email="priya.shah@northwind.example")
    pending = h.request_action().json()["data"]["pending_action_id"]
    h.tool("confirm_device_action", pending_action_id=pending, caller_utterance="hmm")
    h.tool("confirm_device_action", pending_action_id=pending, caller_utterance="yes")


def test_full_call_produces_ordered_audit_trail(h):
    _full_flow(h)
    assert h.events() == ["device.lookup", "ticket.created", "action.requested",
                          "action.confirm_rejected", "action.confirmed", "action.executed"]
    entries = h.admin("audit", conversation_id=CONVO).json()["data"]
    assert all(e["conversation_id"] == CONVO for e in entries)
    confirmed = next(e for e in entries if e["event"] == "action.confirmed")
    assert confirmed["details"]["utterance"] == "yes"  # the exact words that authorized the action
    executed = entries[-1]
    assert executed["details"]["mdm_command_id"].startswith("CMD-")


def test_audit_chain_verifies(h):
    _full_flow(h)
    result = h.admin("audit/verify").json()["data"]
    assert result == {"valid": True, "entries_checked": 6, "first_invalid_seq": None}


def test_tampering_is_detected(h):
    _full_flow(h)
    conn = h.db()
    conn.execute("""UPDATE audit_log SET details = '{"utterance":"no"}' WHERE event = 'action.confirmed'""")
    conn.close()
    result = h.admin("audit/verify").json()["data"]
    assert result["valid"] is False
    assert result["first_invalid_seq"] == 5


def test_audit_rows_cannot_be_deleted(h):
    _full_flow(h)
    conn = h.db()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_log")
    conn.close()


def test_rejected_requests_are_still_audited(h):
    ticket = h.open_ticket()
    h.request_action(caller="marcus.lee@northwind.example", ticket_id=ticket)
    denied = [e for e in h.admin("audit").json()["data"] if e["event"] == "action.denied"]
    assert denied and denied[0]["details"]["reason"] == "OWNER_MISMATCH"
