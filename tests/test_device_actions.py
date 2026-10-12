"""The core safety property: no device action runs without an explicit, fresh confirmation."""
from datetime import timedelta

from app.timeutil import iso, utcnow
from tests.conftest import PRIYA


def _pending(h, **kw) -> dict:
    r = h.request_action(**kw)
    assert r.status_code == 200, r.json()
    return r.json()["data"]


def _confirm(h, pending_id, utterance, **kw):
    return h.tool("confirm_device_action", pending_action_id=pending_id, caller_utterance=utterance, **kw)


def test_request_alone_never_touches_the_device(h):
    data = _pending(h)
    assert data["pending_action_id"].startswith("PA-")
    assert "Just to confirm" in data["readback"] and "NW-1042" in data["readback"]
    assert h.mdm.calls == []
    assert h.device_status("DEV-001") == "active"


def test_confirmed_lock_executes_once_and_is_recorded(h):
    data = _pending(h)
    r = _confirm(h, data["pending_action_id"], "Yes, go ahead")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["status"] == "executed" and body["data"]["mdm_status"] == "completed"
    assert "locked" in body["speakable"]
    assert h.mdm.calls == [("DEV-001", "lock")]
    assert h.device_status("DEV-001") == "locked"

    notes = h.tool("get_ticket", ticket_id=body["data"]["ticket_id"]).json()["data"]["notes"]
    assert "lock sent to NW-1042" in notes[-1]["body"]

    # Replaying the confirmation must not re-run the command.
    r = _confirm(h, data["pending_action_id"], "yes")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACTION_NOT_PENDING"
    assert len(h.mdm.calls) == 1


def test_caller_declines(h):
    data = _pending(h)
    r = _confirm(h, data["pending_action_id"], "No, don't do that")
    assert r.status_code == 200 and r.json()["data"]["status"] == "cancelled"
    assert h.mdm.calls == [] and h.device_status("DEV-001") == "active"


def test_unclear_answers_are_rejected_then_locked_out(h):
    data = _pending(h)
    for remaining in (2, 1):
        r = _confirm(h, data["pending_action_id"], "hmm, what?")
        assert r.status_code == 422
        assert r.json()["error"]["details"]["attempts_remaining"] == remaining
    r = _confirm(h, data["pending_action_id"], "the blue one")
    assert r.json()["error"]["code"] == "CONFIRMATION_LOCKED_OUT"
    assert "technician" in r.json()["speakable"]
    # Even a clear yes is refused now.
    assert _confirm(h, data["pending_action_id"], "yes").status_code == 409
    assert h.mdm.calls == []


def test_wipe_requires_spoken_asset_tag_digits(h):
    data = _pending(h, action="wipe")
    assert data["risk"] == "high" and data["requires_code"] is True
    assert "cannot be undone" in data["readback"]

    r = _confirm(h, data["pending_action_id"], "yes")
    assert r.status_code == 422 and "four digits" in r.json()["speakable"]
    r = _confirm(h, data["pending_action_id"], "yes one zero four three")
    assert r.status_code == 422
    assert h.mdm.calls == []

    r = _confirm(h, data["pending_action_id"], "yes, one zero four two")
    assert r.status_code == 200
    assert h.device_status("DEV-001") == "wiped"


def test_expired_confirmation(h):
    data = _pending(h)
    conn = h.db()
    conn.execute("UPDATE pending_actions SET expires_at = ? WHERE id = ?",
                 (iso(utcnow() - timedelta(seconds=1)), data["pending_action_id"]))
    conn.close()
    r = _confirm(h, data["pending_action_id"], "yes")
    assert r.status_code == 410 and r.json()["error"]["code"] == "CONFIRMATION_EXPIRED"
    assert h.mdm.calls == []
    assert _confirm(h, data["pending_action_id"], "yes").status_code == 409


def test_confirmation_must_come_from_the_same_conversation(h):
    data = _pending(h)
    r = _confirm(h, data["pending_action_id"], "yes", conversation_id="conv_attacker")
    assert r.status_code == 403 and r.json()["error"]["code"] == "CONVERSATION_MISMATCH"
    assert h.mdm.calls == []


def test_only_the_owner_can_request_actions(h):
    ticket = h.open_ticket()
    r = h.request_action(caller="marcus.lee@northwind.example", ticket_id=ticket)
    assert r.status_code == 403 and r.json()["error"]["code"] == "OWNER_MISMATCH"
    assert "action.denied" in h.events()


def test_ticket_must_match_device(h):
    ticket = h.open_ticket(device_id="DEV-002")
    r = h.request_action(device_id="DEV-001", ticket_id=ticket)
    assert r.status_code == 409 and r.json()["error"]["code"] == "TICKET_DEVICE_MISMATCH"


def test_retired_device_and_double_lock_are_refused(h):
    r = h.request_action(device_id="DEV-005", caller="aiko.tanaka@northwind.example")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DEVICE_RETIRED"

    data = _pending(h)
    _confirm(h, data["pending_action_id"], "yes")
    r = h.request_action()
    assert r.json()["error"]["code"] == "ALREADY_LOCKED"


def test_offline_device_command_is_queued(h):
    data = _pending(h, device_id="DEV-004", caller="jordan.rivera@northwind.example")
    assert "offline" in data["readback"]
    r = _confirm(h, data["pending_action_id"], "yes")
    assert r.json()["data"]["mdm_status"] == "queued"
    assert "queued" in r.json()["speakable"]
    assert h.device_status("DEV-004") == "active"  # not locked until it actually checks in


def test_new_request_supersedes_old_one(h):
    ticket = h.open_ticket()
    first = _pending(h, ticket_id=ticket)
    second = _pending(h, action="restart", ticket_id=ticket)
    assert _confirm(h, first["pending_action_id"], "yes").status_code == 409
    assert _confirm(h, second["pending_action_id"], "yes").status_code == 200
    assert h.mdm.calls == [("DEV-001", "restart")]


def test_cancel_tool(h):
    data = _pending(h)
    r = h.tool("cancel_device_action", pending_action_id=data["pending_action_id"])
    assert r.status_code == 200
    assert _confirm(h, data["pending_action_id"], "yes").status_code == 409
    assert h.tool("cancel_device_action", pending_action_id="PA-nope").status_code == 404


def test_mdm_outage_fails_safely(make_harness):
    h = make_harness(mdm_fault="outage")
    data = _pending(h)
    r = _confirm(h, data["pending_action_id"], "yes")
    assert r.status_code == 502
    body = r.json()
    assert body["error"]["code"] == "MDM_UNAVAILABLE"
    assert "nothing has been changed" in body["speakable"]
    assert len(h.mdm.calls) == h.settings.mdm_retries
    assert h.device_status("DEV-001") == "active"
    notes = h.tool("get_ticket", ticket_id=body["error"]["details"]["ticket_id"]).json()["data"]["notes"]
    assert "MDM unavailable" in notes[-1]["body"]
    # A failed action can't be silently re-confirmed; the agent has to start over.
    assert _confirm(h, data["pending_action_id"], "yes").status_code == 409


def test_transient_mdm_failure_is_retried(make_harness):
    h = make_harness(mdm_fault="flaky")
    data = _pending(h)
    r = _confirm(h, data["pending_action_id"], "yes")
    assert r.status_code == 200
    assert len(h.mdm.calls) == 2
    assert h.device_status("DEV-001") == "locked"


def test_unknown_action_is_rejected(h):
    ticket = h.open_ticket()
    r = h.tool("request_device_action", device_id="DEV-001", action="format_c_drive", ticket_id=ticket,
               caller_email=PRIYA)
    assert r.status_code == 422
