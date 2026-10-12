import sqlite3
from contextlib import contextmanager

from app.seed_data import DEVICES, EMPLOYEES

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    department  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id              TEXT PRIMARY KEY,
    asset_tag       TEXT NOT NULL UNIQUE,
    serial          TEXT NOT NULL UNIQUE,
    model           TEXT NOT NULL,
    os              TEXT NOT NULL,
    os_version      TEXT NOT NULL,
    owner_id        TEXT NOT NULL REFERENCES employees(id),
    status          TEXT NOT NULL CHECK (status IN ('active', 'locked', 'wiped', 'retired')),
    online          INTEGER NOT NULL,
    last_check_in   TEXT NOT NULL,
    disk_encrypted  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id               TEXT PRIMARY KEY,
    device_id        TEXT NOT NULL REFERENCES devices(id),
    requester_id     TEXT NOT NULL REFERENCES employees(id),
    summary          TEXT NOT NULL,
    category         TEXT NOT NULL,
    priority         TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'open',
    conversation_id  TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  TEXT NOT NULL REFERENCES tickets(id),
    ts         TEXT NOT NULL,
    author     TEXT NOT NULL,
    body       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id               TEXT PRIMARY KEY,
    device_id        TEXT NOT NULL REFERENCES devices(id),
    ticket_id        TEXT NOT NULL REFERENCES tickets(id),
    action           TEXT NOT NULL,
    risk             TEXT NOT NULL,
    confirmation_code TEXT,
    conversation_id  TEXT,
    status           TEXT NOT NULL CHECK (status IN
                     ('pending', 'executing', 'executed', 'cancelled', 'expired', 'failed', 'locked_out')),
    attempts         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    resolved_at      TEXT,
    mdm_command_id   TEXT
);

-- Append-only, hash-chained: each row's hash covers the previous row's hash.
CREATE TABLE IF NOT EXISTS audit_log (
    seq              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT NOT NULL,
    request_id       TEXT,
    conversation_id  TEXT,
    actor            TEXT NOT NULL,
    event            TEXT NOT NULL,
    target           TEXT,
    details          TEXT NOT NULL,
    prev_hash        TEXT NOT NULL,
    hash             TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


def connect(path: str) -> sqlite3.Connection:
    # Autocommit mode; writes go through `transaction()` so we control BEGIN IMMEDIATE.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db(path: str, seed: bool = True) -> None:
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        if seed and conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 0:
            with transaction(conn):
                conn.executemany("INSERT INTO employees VALUES (:id, :name, :email, :department)", EMPLOYEES)
                conn.executemany(
                    "INSERT INTO devices VALUES (:id, :asset_tag, :serial, :model, :os, :os_version, "
                    ":owner_id, :status, :online, :last_check_in, :disk_encrypted)",
                    DEVICES,
                )
    finally:
        conn.close()
