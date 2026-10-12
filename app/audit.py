"""Tamper-evident audit log.

Each entry stores sha256(prev_hash | fields...). Editing or deleting any past row breaks
every hash after it, which `verify()` detects. Must be called inside a write transaction
so the read of the previous hash and the insert are atomic.
"""
import hashlib
import json
import sqlite3
from dataclasses import dataclass

from app.timeutil import iso, utcnow

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    conversation_id: str | None = None
    actor: str = "voice-agent"


def _digest(prev_hash: str, ts: str, request_id: str | None, conversation_id: str | None,
            actor: str, event: str, target: str | None, details: str) -> str:
    payload = "|".join([prev_hash, ts, request_id or "", conversation_id or "", actor, event, target or "", details])
    return hashlib.sha256(payload.encode()).hexdigest()


def record(conn: sqlite3.Connection, ctx: RequestContext, event: str, target: str | None = None,
           **details) -> None:
    row = conn.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
    prev_hash = row["hash"] if row else GENESIS_HASH
    ts = iso(utcnow())
    details_json = json.dumps(details, sort_keys=True, separators=(",", ":"), default=str)
    entry_hash = _digest(prev_hash, ts, ctx.request_id, ctx.conversation_id, ctx.actor, event, target, details_json)
    conn.execute(
        "INSERT INTO audit_log (ts, request_id, conversation_id, actor, event, target, details, prev_hash, hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, ctx.request_id, ctx.conversation_id, ctx.actor, event, target, details_json, prev_hash, entry_hash),
    )


def list_entries(conn: sqlite3.Connection, conversation_id: str | None = None, limit: int = 100) -> list[dict]:
    if conversation_id:
        rows = conn.execute("SELECT * FROM audit_log WHERE conversation_id = ? ORDER BY seq LIMIT ?",
                            (conversation_id, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM (SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?) ORDER BY seq",
                            (limit,)).fetchall()
    return [{**dict(r), "details": json.loads(r["details"])} for r in rows]


def verify(conn: sqlite3.Connection) -> dict:
    prev_hash = GENESIS_HASH
    count = 0
    for r in conn.execute("SELECT * FROM audit_log ORDER BY seq"):
        expected = _digest(prev_hash, r["ts"], r["request_id"], r["conversation_id"], r["actor"],
                           r["event"], r["target"], r["details"])
        if r["prev_hash"] != prev_hash or r["hash"] != expected:
            return {"valid": False, "entries_checked": count, "first_invalid_seq": r["seq"]}
        prev_hash = r["hash"]
        count += 1
    return {"valid": True, "entries_checked": count, "first_invalid_seq": None}
