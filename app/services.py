"""Business logic. Each function returns (data, speakable) or raises a ServiceDeskError.

Audit entries are written in the same transaction as the state change they describe. When a
request is rejected we still commit the audit entry first, then raise.
"""
import secrets
import sqlite3
import time
from datetime import timedelta

from app import audit, confirmation
from app.audit import RequestContext
from app.config import Settings
from app.db import transaction
from app.errors import (Conflict, ConfirmationExpired, ConfirmationRejected, Forbidden, InvalidInput,
                        NotFound, UpstreamUnavailable)
from app.mdm import MDMClient, MDMUnavailable
from app.timeutil import iso, parse_iso, utcnow

ACTIONS = {
    "restart": {"risk": "low", "verb": "restart"},
    "lock": {"risk": "medium", "verb": "remotely lock"},
    "wipe": {"risk": "high", "verb": "permanently erase"},
}
PRIORITY_ORDER = ["low", "medium", "high", "critical"]


# ---------- helpers ----------

def normalize_asset_tag(raw: str) -> str:
    """'nw 1042', 'NW1042', '1042' -> 'NW-1042'."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise InvalidInput(f"Asset tag {raw!r} has no digits", code="INVALID_ASSET_TAG",
                           speakable="Asset tags look like N W dash and four digits. Could you read it again?")
    return f"NW-{digits}"


def normalize_ticket_id(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise InvalidInput(f"Ticket id {raw!r} has no digits", code="INVALID_TICKET_ID",
                           speakable="Ticket numbers start with I N C followed by four digits. Could you repeat it?")
    return f"INC-{digits}"


def public_device(d: sqlite3.Row) -> dict:
    # Never expose the full serial over a voice channel.
    return {
        "device_id": d["id"], "asset_tag": d["asset_tag"], "model": d["model"],
        "os": f'{d["os"]} {d["os_version"]}', "status": d["status"], "online": bool(d["online"]),
        "last_check_in": d["last_check_in"], "serial_last4": d["serial"][-4:],
        "disk_encrypted": bool(d["disk_encrypted"]),
    }


def _employee_by_email(conn, email: str):
    return conn.execute("SELECT * FROM employees WHERE email = ?", (email.strip().lower(),)).fetchone()


def _device(conn, device_id: str):
    d = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id.strip().upper(),)).fetchone()
    if not d:
        raise NotFound(f"Device {device_id} not found", code="DEVICE_NOT_FOUND",
                       speakable="I couldn't find that device. Let me look it up again by your email or asset tag.")
    return d


def _ticket(conn, ticket_id: str):
    t = conn.execute("SELECT * FROM tickets WHERE id = ?", (normalize_ticket_id(ticket_id),)).fetchone()
    if not t:
        raise NotFound(f"Ticket {ticket_id} not found", code="TICKET_NOT_FOUND",
                       speakable="I couldn't find a ticket with that number. Could you read it to me again?")
    return t


def _add_note(conn, ticket_id: str, body: str, author: str = "voice-agent") -> None:
    now = iso(utcnow())
    conn.execute("INSERT INTO ticket_notes (ticket_id, ts, author, body) VALUES (?, ?, ?, ?)",
                 (ticket_id, now, author, body))
    conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now, ticket_id))


def _article(noun: str) -> str:
    return "an" if noun[0].lower() in "aeiou" else "a"


def _list_phrase(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f", and {items[-1]}"


# ---------- device lookup ----------

def lookup_devices(conn, ctx: RequestContext, email: str | None, asset_tag: str | None):
    if not email and not asset_tag:
        raise InvalidInput("email or asset_tag is required", code="MISSING_IDENTIFIER",
                           speakable="Could you tell me your work email, or the asset tag on the device?")
    with transaction(conn):
        if asset_tag:
            tag = normalize_asset_tag(asset_tag)
            rows = conn.execute("SELECT * FROM devices WHERE asset_tag = ?", (tag,)).fetchall()
            employee = (conn.execute("SELECT * FROM employees WHERE id = ?", (rows[0]["owner_id"],)).fetchone()
                        if rows else None)
            key = {"asset_tag": tag}
        else:
            employee = _employee_by_email(conn, email)
            rows = (conn.execute("SELECT * FROM devices WHERE owner_id = ? ORDER BY id", (employee["id"],)).fetchall()
                    if employee else [])
            key = {"email": email.strip().lower()}
        audit.record(conn, ctx, "device.lookup", target=rows[0]["id"] if len(rows) == 1 else None,
                     found=len(rows), **key)

    if not employee or not rows:
        what = "device with that asset tag" if asset_tag else "employee with that email"
        raise NotFound(f"No {what}", code="LOOKUP_NO_MATCH",
                       speakable=f"I couldn't find a {what}. Could you spell it out for me?")

    devices = [public_device(r) for r in rows]
    described = [f'{_article(d["model"])} {d["model"]}, asset tag {d["asset_tag"]}' + ("" if d["status"] == "active" else f' ({d["status"]})')
                 for d in devices]
    noun = "device" if len(devices) == 1 else f"{len(devices)} devices"
    speakable = f'I found {noun} for {employee["name"]}: {_list_phrase(described)}.'
    data = {"employee": {"id": employee["id"], "name": employee["name"], "email": employee["email"],
                         "department": employee["department"]},
            "devices": devices}
    return data, speakable


# ---------- tickets ----------

def create_ticket(conn, ctx: RequestContext, *, device_id: str, caller_email: str, summary: str,
                  category: str, priority: str):
    with transaction(conn):
        device = _device(conn, device_id)
        requester = _employee_by_email(conn, caller_email)
        if not requester:
            raise NotFound("Caller not found", code="CALLER_NOT_FOUND",
                           speakable="I couldn't match your email to an employee record. Could you spell it for me?")

        # Idempotency: agents sometimes retry tool calls. One open ticket per device per conversation.
        if ctx.conversation_id:
            existing = conn.execute(
                "SELECT * FROM tickets WHERE conversation_id = ? AND device_id = ? AND status = 'open'",
                (ctx.conversation_id, device["id"])).fetchone()
            if existing:
                audit.record(conn, ctx, "ticket.deduplicated", target=existing["id"])
                return ({**dict(existing), "deduplicated": True},
                        f'You already have ticket {existing["id"]} open for this, so I\'ll use that one.')

        # Lost or stolen devices are a potential data exposure: never below high.
        if category == "lost_or_stolen" and PRIORITY_ORDER.index(priority) < PRIORITY_ORDER.index("high"):
            priority = "high"

        next_num = conn.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(id, 5) AS INTEGER)), 1000) + 1 FROM tickets").fetchone()[0]
        ticket_id = f"INC-{next_num}"
        now = iso(utcnow())
        conn.execute(
            "INSERT INTO tickets (id, device_id, requester_id, summary, category, priority, status, "
            "conversation_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)",
            (ticket_id, device["id"], requester["id"], summary, category, priority, ctx.conversation_id, now, now))
        _add_note(conn, ticket_id, f"Ticket opened by voice agent. Caller: {requester['email']}.")
        audit.record(conn, ctx, "ticket.created", target=ticket_id, device_id=device["id"],
                     category=category, priority=priority, requester=requester["id"])
        ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()

    return ({**dict(ticket), "deduplicated": False},
            f"I've opened ticket {ticket_id} with {priority} priority.")


def get_ticket(conn, ctx: RequestContext, ticket_id: str):
    with transaction(conn):
        t = _ticket(conn, ticket_id)
        notes = conn.execute("SELECT ts, author, body FROM ticket_notes WHERE ticket_id = ? ORDER BY id",
                             (t["id"],)).fetchall()
        audit.record(conn, ctx, "ticket.viewed", target=t["id"])
    data = {**dict(t), "notes": [dict(n) for n in notes]}
    return data, f'Ticket {t["id"]} is {t["status"]}, {t["priority"]} priority: {t["summary"]}. Latest note: {notes[-1]["body"]}'


# ---------- device actions: request -> confirm ----------

def request_device_action(conn, ctx: RequestContext, settings: Settings, *, device_id: str, action: str,
                          ticket_id: str, caller_email: str):
    spec = ACTIONS[action]
    denial = None
    with transaction(conn):
        device = _device(conn, device_id)
        ticket = _ticket(conn, ticket_id)
        caller = _employee_by_email(conn, caller_email)

        if ticket["device_id"] != device["id"]:
            denial = Conflict("Ticket is for a different device", code="TICKET_DEVICE_MISMATCH",
                              speakable="That ticket is for a different device. Let me open a ticket for this one first.")
        elif ticket["status"] != "open":
            denial = Conflict("Ticket is not open", code="TICKET_NOT_OPEN",
                              speakable="That ticket is already closed, so I'll need to open a new one.")
        elif not caller or caller["id"] != device["owner_id"]:
            # Only the device owner may authorize remote actions over the phone.
            denial = Forbidden("Caller does not own device", code="OWNER_MISMATCH",
                               speakable="For security I can only take action on a device registered to you. "
                                         "I've logged the request and a technician can help verify ownership.")
        elif device["status"] in ("retired", "wiped"):
            denial = Conflict(f"Device is {device['status']}", code=f"DEVICE_{device['status'].upper()}",
                              speakable=f"That device is already {device['status']}, so there's nothing I can do to it remotely.")
        elif action == "lock" and device["status"] == "locked":
            denial = Conflict("Device already locked", code="ALREADY_LOCKED",
                              speakable="Good news: that device is already locked.")

        if denial:
            audit.record(conn, ctx, "action.denied", target=device["id"], action=action, ticket_id=ticket["id"],
                         reason=denial.code, caller=caller_email)
        else:
            # A fresh request supersedes any earlier unconfirmed request for the same device.
            for old in conn.execute("SELECT id FROM pending_actions WHERE device_id = ? AND status = 'pending'",
                                    (device["id"],)).fetchall():
                conn.execute("UPDATE pending_actions SET status = 'cancelled', resolved_at = ? WHERE id = ?",
                             (iso(utcnow()), old["id"]))
                audit.record(conn, ctx, "action.superseded", target=old["id"])

            now = utcnow()
            pending_id = f"PA-{secrets.token_hex(4)}"
            code = "".join(ch for ch in device["asset_tag"] if ch.isdigit()) if spec["risk"] == "high" else None
            conn.execute(
                "INSERT INTO pending_actions (id, device_id, ticket_id, action, risk, confirmation_code, "
                "conversation_id, status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (pending_id, device["id"], ticket["id"], action, spec["risk"], code, ctx.conversation_id,
                 iso(now), iso(now + timedelta(seconds=settings.confirmation_ttl_seconds))))
            audit.record(conn, ctx, "action.requested", target=pending_id, device_id=device["id"],
                         action=action, risk=spec["risk"], ticket_id=ticket["id"])
            expires_at = iso(now + timedelta(seconds=settings.confirmation_ttl_seconds))

    if denial:
        raise denial

    readback = f'Just to confirm: you want me to {spec["verb"]} the {device["model"]}, asset tag {device["asset_tag"]}, ' \
               f'under ticket {ticket["id"]}.'
    if not device["online"]:
        readback += " It's offline right now, so this will happen the next time it connects."
    if spec["risk"] == "high":
        readback += (" This deletes everything on the device and cannot be undone. "
                     "To confirm, please say yes, followed by the four digits of the asset tag.")
    else:
        readback += " Shall I go ahead?"

    data = {"pending_action_id": pending_id, "action": action, "risk": spec["risk"],
            "requires_code": spec["risk"] == "high", "expires_at": expires_at, "readback": readback,
            "agent_instructions": "Read `readback` to the caller word for word, then wait. Pass the caller's exact "
                                  "reply to confirm_device_action. Do not paraphrase or answer for them."}
    return data, readback


def _send_with_retry(mdm: MDMClient, settings: Settings, device, action: str) -> dict:
    for attempt in range(settings.mdm_retries):
        try:
            return mdm.send_command(device["id"], action, bool(device["online"]))
        except MDMUnavailable:
            if attempt == settings.mdm_retries - 1:
                raise
            time.sleep(settings.mdm_backoff_seconds * (2 ** attempt))
    raise AssertionError("unreachable")


def confirm_device_action(conn, ctx: RequestContext, settings: Settings, mdm: MDMClient, *,
                          pending_action_id: str, caller_utterance: str):
    rejection = None
    with transaction(conn):
        pa = conn.execute("SELECT * FROM pending_actions WHERE id = ?", (pending_action_id.strip(),)).fetchone()
        if not pa:
            raise NotFound("Pending action not found", code="PENDING_ACTION_NOT_FOUND",
                           speakable="I don't have that request on file anymore. Let me set it up again.")
        if pa["status"] != "pending":
            raise Conflict(f"Action is {pa['status']}", code="ACTION_NOT_PENDING",
                           speakable=f"That request is already {pa['status'].replace('_', ' ')}, so I won't run it again.")
        if pa["conversation_id"] and ctx.conversation_id != pa["conversation_id"]:
            audit.record(conn, ctx, "action.confirm_denied", target=pa["id"], reason="CONVERSATION_MISMATCH")
            rejection = Forbidden("Confirmation from a different conversation", code="CONVERSATION_MISMATCH",
                                  speakable="That request was started on a different call, so I can't confirm it here.")
        elif utcnow() > parse_iso(pa["expires_at"]):
            conn.execute("UPDATE pending_actions SET status = 'expired', resolved_at = ? WHERE id = ?",
                         (iso(utcnow()), pa["id"]))
            audit.record(conn, ctx, "action.expired", target=pa["id"])
            rejection = ConfirmationExpired("Confirmation window elapsed")
        else:
            verdict = confirmation.interpret(caller_utterance)
            code_ok = pa["confirmation_code"] is None or confirmation.code_matches(caller_utterance,
                                                                                 pa["confirmation_code"])
            if verdict == "declined":
                conn.execute("UPDATE pending_actions SET status = 'cancelled', resolved_at = ? WHERE id = ?",
                             (iso(utcnow()), pa["id"]))
                _add_note(conn, pa["ticket_id"], f"Caller declined {pa['action']}. No action taken.")
                audit.record(conn, ctx, "action.cancelled", target=pa["id"], reason="caller_declined",
                             utterance=caller_utterance)
                return ({"pending_action_id": pa["id"], "status": "cancelled"},
                        "No problem, I've cancelled that. Nothing was changed on the device.")
            if verdict == "unclear" or not code_ok:
                attempts = pa["attempts"] + 1
                reason = "unclear" if verdict == "unclear" else "code_mismatch"
                if attempts >= settings.max_confirmation_attempts:
                    conn.execute("UPDATE pending_actions SET status = 'locked_out', attempts = ?, resolved_at = ? "
                                 "WHERE id = ?", (attempts, iso(utcnow()), pa["id"]))
                    _add_note(conn, pa["ticket_id"],
                              f"{pa['action']} not confirmed after {attempts} attempts. Escalated to a technician.")
                    audit.record(conn, ctx, "action.locked_out", target=pa["id"], attempts=attempts,
                                 reason=reason, utterance=caller_utterance)
                    rejection = ConfirmationRejected(
                        "Too many failed confirmations", code="CONFIRMATION_LOCKED_OUT",
                        speakable=f"For safety I can't take that action on this call. A technician will follow up "
                                  f"on ticket {pa['ticket_id']}.")
                else:
                    conn.execute("UPDATE pending_actions SET attempts = ? WHERE id = ?", (attempts, pa["id"]))
                    audit.record(conn, ctx, "action.confirm_rejected", target=pa["id"], attempts=attempts,
                                 reason=reason, utterance=caller_utterance)
                    rejection = ConfirmationRejected(
                        "Confirmation not clear", details={"attempts_remaining": settings.max_confirmation_attempts - attempts},
                        speakable=("That code didn't match. Please say yes, followed by the four digits of the asset tag."
                                   if reason == "code_mismatch" else
                                   "Sorry, I need a clear yes or no. Should I go ahead?"))
            else:
                # Claim the action atomically so a duplicate confirm can never double-execute.
                conn.execute("UPDATE pending_actions SET status = 'executing' WHERE id = ?", (pa["id"],))
                audit.record(conn, ctx, "action.confirmed", target=pa["id"], utterance=caller_utterance)
                device = _device(conn, pa["device_id"])

    if rejection:
        raise rejection

    # MDM call happens outside the DB transaction so a slow upstream never holds the write lock.
    try:
        result = _send_with_retry(mdm, settings, device, pa["action"])
    except Exception as exc:
        # Never leave an action stuck in 'executing': record the failure, then surface it.
        reason = "MDM unavailable" if isinstance(exc, MDMUnavailable) else "unexpected error"
        with transaction(conn):
            conn.execute("UPDATE pending_actions SET status = 'failed', resolved_at = ? WHERE id = ?",
                         (iso(utcnow()), pa["id"]))
            _add_note(conn, pa["ticket_id"], f"{pa['action']} failed: {reason}. Needs technician.")
            audit.record(conn, ctx, "action.failed", target=pa["id"], error=type(exc).__name__, reason=reason)
        if isinstance(exc, MDMUnavailable):
            raise UpstreamUnavailable(str(exc), details={"ticket_id": pa["ticket_id"]}) from exc
        raise

    new_status = {"lock": "locked", "wipe": "wiped"}.get(pa["action"])
    with transaction(conn):
        conn.execute("UPDATE pending_actions SET status = 'executed', resolved_at = ?, mdm_command_id = ? WHERE id = ?",
                     (iso(utcnow()), result["command_id"], pa["id"]))
        if new_status and result["status"] == "completed":
            conn.execute("UPDATE devices SET status = ? WHERE id = ?", (new_status, device["id"]))
        _add_note(conn, pa["ticket_id"],
                  f"{pa['action']} sent to {device['asset_tag']} (MDM {result['command_id']}, {result['status']}).")
        audit.record(conn, ctx, "action.executed", target=pa["id"], device_id=device["id"], action=pa["action"],
                     mdm_command_id=result["command_id"], mdm_status=result["status"])

    verb = {"restart": "restarting", "lock": "locked", "wipe": "erasing"}[pa["action"]]
    if result["status"] == "queued":
        speakable = f"Done. The {pa['action']} command is queued and will run as soon as the device comes online."
    elif pa["action"] == "restart":
        speakable = "Done. Your device is restarting now."
    else:
        speakable = f"Done. Your {device['model']} is {verb} now."
    speakable += f" I've added this to ticket {pa['ticket_id']}."
    return ({"pending_action_id": pa["id"], "status": "executed", "mdm_command_id": result["command_id"],
             "mdm_status": result["status"], "ticket_id": pa["ticket_id"]}, speakable)


def cancel_device_action(conn, ctx: RequestContext, *, pending_action_id: str):
    with transaction(conn):
        pa = conn.execute("SELECT * FROM pending_actions WHERE id = ?", (pending_action_id.strip(),)).fetchone()
        if not pa:
            raise NotFound("Pending action not found", code="PENDING_ACTION_NOT_FOUND",
                           speakable="There's nothing pending to cancel.")
        if pa["status"] != "pending":
            raise Conflict(f"Action is {pa['status']}", code="ACTION_NOT_PENDING",
                           speakable=f"That request is already {pa['status'].replace('_', ' ')}.")
        conn.execute("UPDATE pending_actions SET status = 'cancelled', resolved_at = ? WHERE id = ?",
                     (iso(utcnow()), pa["id"]))
        _add_note(conn, pa["ticket_id"], f"{pa['action']} cancelled before confirmation.")
        audit.record(conn, ctx, "action.cancelled", target=pa["id"], reason="cancel_tool")
    return {"pending_action_id": pa["id"], "status": "cancelled"}, "Okay, I've cancelled that. Nothing was changed."

