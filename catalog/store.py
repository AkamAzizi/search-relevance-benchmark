"""Incremental catalog state (spec 6.1). Products are never hard-deleted."""
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from catalog.record import ENRICHMENT_FIELDS, enrichment_input_hash, source_payload_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS product_version (
    product_id            TEXT    NOT NULL,
    version               INTEGER NOT NULL,
    source_payload_hash   TEXT    NOT NULL,
    enrichment_input_hash TEXT    NOT NULL,
    payload               TEXT    NOT NULL,
    created_at            TEXT    NOT NULL,
    PRIMARY KEY (product_id, version)
);
CREATE TABLE IF NOT EXISTS product_state (
    product_id      TEXT PRIMARY KEY,
    current_version INTEGER NOT NULL,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    deleted_at      TEXT
);
CREATE TABLE IF NOT EXISTS enrichment_cache (
    enrichment_input_hash TEXT PRIMARY KEY,
    input_payload         TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    result                TEXT,
    raw_response          TEXT,
    created_at            TEXT NOT NULL,
    completed_at          TEXT
);
CREATE TABLE IF NOT EXISTS product_enrichment (
    product_id            TEXT NOT NULL,
    enrichment_input_hash TEXT NOT NULL,
    first_requested       TEXT NOT NULL,
    PRIMARY KEY (product_id, enrichment_input_hash),
    FOREIGN KEY (enrichment_input_hash)
        REFERENCES enrichment_cache(enrichment_input_hash)
);
"""


@dataclass
class SyncReport:
    new: int = 0
    source_changed: int = 0
    enrichment_stale: int = 0
    unchanged: int = 0
    disappeared: int = 0
    enrichment_jobs: int = 0


def open_store(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _write_version(conn, pid, version, sph, eih, rec, now) -> None:
    conn.execute(
        "INSERT INTO product_version VALUES (?,?,?,?,?,?)",
        (pid, version, sph, eih, json.dumps(rec, ensure_ascii=False), now),
    )


def _enqueue(conn, pid, eih, rec, now) -> bool:
    """Create one cacheable job per unique enrichment input, then link the product."""
    payload = json.dumps(
        {key: rec[key] for key in ENRICHMENT_FIELDS},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    cur = conn.execute(
        "INSERT OR IGNORE INTO enrichment_cache "
        "(enrichment_input_hash, input_payload, status, created_at) "
        "VALUES (?,?,'pending',?)",
        (eih, payload, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO product_enrichment VALUES (?,?,?)", (pid, eih, now)
    )
    return cur.rowcount > 0


def sync(conn: sqlite3.Connection, records: list[dict], now: str) -> SyncReport:
    report = SyncReport()
    seen: set[str] = set()

    for rec in records:
        pid = rec["product_id"]
        seen.add(pid)
        sph, eih = source_payload_hash(rec), enrichment_input_hash(rec)

        state = conn.execute(
            "SELECT current_version FROM product_state WHERE product_id=?", (pid,)
        ).fetchone()

        if state is None:
            _write_version(conn, pid, 1, sph, eih, rec, now)
            conn.execute(
                "INSERT INTO product_state VALUES (?,?,?,?,NULL)", (pid, 1, now, now)
            )
            report.new += 1
            report.enrichment_jobs += int(_enqueue(conn, pid, eih, rec, now))
            continue

        current = conn.execute(
            "SELECT source_payload_hash, enrichment_input_hash "
            "FROM product_version WHERE product_id=? AND version=?",
            (pid, state[0]),
        ).fetchone()

        if current[0] == sph and current[1] == eih:
            conn.execute(
                "UPDATE product_state SET last_seen=?, deleted_at=NULL WHERE product_id=?",
                (now, pid),
            )
            report.unchanged += 1
            continue

        version = state[0] + 1
        _write_version(conn, pid, version, sph, eih, rec, now)
        conn.execute(
            "UPDATE product_state SET current_version=?, last_seen=?, deleted_at=NULL "
            "WHERE product_id=?",
            (version, now, pid),
        )
        if current[1] != eih:
            report.enrichment_stale += 1
            report.enrichment_jobs += int(_enqueue(conn, pid, eih, rec, now))
        else:
            report.source_changed += 1

    live = conn.execute(
        "SELECT product_id FROM product_state WHERE deleted_at IS NULL"
    ).fetchall()
    for (pid,) in live:
        if pid not in seen:
            conn.execute(
                "UPDATE product_state SET deleted_at=? WHERE product_id=?", (now, pid)
            )
            report.disappeared += 1

    conn.commit()
    return report


def pending_enrichment(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return conn.execute(
        "SELECT enrichment_input_hash, input_payload FROM enrichment_cache "
        "WHERE status='pending' ORDER BY enrichment_input_hash"
    ).fetchall()


def complete_enrichment(conn: sqlite3.Connection, enrichment_input_hash: str,
                        result: dict, raw_response: str, now: str) -> None:
    cur = conn.execute(
        "UPDATE enrichment_cache SET status='completed', result=?, raw_response=?, "
        "completed_at=? WHERE enrichment_input_hash=? AND status='pending'",
        (json.dumps(result, ensure_ascii=False), raw_response, now, enrichment_input_hash),
    )
    if cur.rowcount != 1:
        raise KeyError(f"no pending enrichment input {enrichment_input_hash}")
    conn.commit()


def current_live_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM product_state WHERE deleted_at IS NULL"
    ).fetchone()[0]
