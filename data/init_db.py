"""
Initialises the SQLite database with all tables needed for the full pipeline.
Run once: python data/init_db.py
"""
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_PATH", "data/revenue_recovery.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_failure_events (
    event_id                  TEXT PRIMARY KEY,
    customer_id               TEXT NOT NULL,
    timestamp                 TEXT NOT NULL,
    amount                    REAL NOT NULL,
    currency                  TEXT NOT NULL DEFAULT 'INR',
    payment_method            TEXT NOT NULL,
    gateway_response_code     TEXT NOT NULL,
    attempt_number            INTEGER NOT NULL DEFAULT 1,
    is_subscription_renewal   INTEGER NOT NULL DEFAULT 0,
    customer_contact_opt_in   INTEGER NOT NULL DEFAULT 1,
    do_not_contact            INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS checkout_abandonment_events (
    event_id                        TEXT PRIMARY KEY,
    customer_id                     TEXT NOT NULL,
    timestamp                       TEXT NOT NULL,
    cart_value                      REAL NOT NULL,
    currency                        TEXT NOT NULL DEFAULT 'INR',
    stage_reached                   TEXT NOT NULL,
    device_type                     TEXT NOT NULL,
    time_since_last_activity_minutes INTEGER NOT NULL,
    is_repeat_customer              INTEGER NOT NULL DEFAULT 0,
    customer_contact_opt_in         INTEGER NOT NULL DEFAULT 1,
    do_not_contact                  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cases (
    case_id                   TEXT PRIMARY KEY,
    leak_type                 TEXT NOT NULL,
    event_id                  TEXT NOT NULL,
    customer_id               TEXT NOT NULL,
    amount                    REAL NOT NULL,
    currency                  TEXT NOT NULL DEFAULT 'INR',
    status                    TEXT NOT NULL DEFAULT 'open',   -- open | recovered | suppressed | escalated
    created_at                TEXT NOT NULL,
    closed_at                 TEXT
);

CREATE TABLE IF NOT EXISTS diagnosis_results (
    case_id                   TEXT PRIMARY KEY,
    leak_type                 TEXT NOT NULL,
    root_cause                TEXT NOT NULL,
    confidence                REAL NOT NULL,
    recommended_intervention  TEXT NOT NULL,
    reasoning                 TEXT NOT NULL,
    requires_human_escalation INTEGER NOT NULL DEFAULT 0,
    diagnosis_corrected       INTEGER NOT NULL DEFAULT 0,
    created_at                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    stage         TEXT NOT NULL,   -- detection | diagnosis | rule_check | execution | outcome
    rule_name     TEXT,            -- populated for rule_check stage
    result        TEXT NOT NULL,   -- pass | fail | info
    detail        TEXT             -- free-text, audit-only
);
"""


def init_db(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Database initialised at {db_path}")


if __name__ == "__main__":
    init_db()
