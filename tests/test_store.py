import sqlite3

import pytest

from catalog.record import normalize
from catalog.store import (complete_enrichment, current_live_count, open_store,
                           pending_enrichment, sync)


def raw(pid, title="Bomber Jacket", price="1299.00", tags=None):
    return {"id": pid, "handle": f"h{pid}", "title": title,
            "body_html": "<p>bomberjacka</p>", "vendor": "Carhartt WIP",
            "product_type": "Jackor", "tags": tags or ["Herr"], "options": [],
            "variants": [{"title": "M", "price": price}], "images": [],
            "updated_at": "2026-01-01T00:00:00Z"}


def recs(*raws):
    return [normalize(r) for r in raws]


def test_first_run_inserts_and_enqueues_enrichment(tmp_path):
    conn = open_store(tmp_path / "s.db")
    report = sync(conn, recs(raw(1), raw(2, title="Rain Coat")),
                  now="2026-08-01T00:00:00Z")
    assert (report.new, report.unchanged, report.enrichment_jobs) == (2, 0, 2)
    assert len(pending_enrichment(conn)) == 2


def test_identical_enrichment_inputs_share_one_cached_job(tmp_path):
    conn = open_store(tmp_path / "s.db")
    report = sync(conn, recs(raw(1), raw(2)), now="2026-08-01T00:00:00Z")
    assert report.new == 2
    assert report.enrichment_jobs == 1
    assert len(pending_enrichment(conn)) == 1


def test_second_identical_run_is_a_complete_no_op(tmp_path):
    """The acceptance test from spec 6.1. Note it asserts zero NEW VERSIONS and zero
    ENRICHMENT JOBS -- not zero database updates, because an unchanged record
    legitimately touches last_seen."""
    conn = open_store(tmp_path / "s.db")
    records = recs(raw(1), raw(2))
    sync(conn, records, now="2026-08-01T00:00:00Z")
    report = sync(conn, records, now="2026-08-02T00:00:00Z")
    assert report.new == 0
    assert report.source_changed == 0
    assert report.enrichment_stale == 0
    assert report.enrichment_jobs == 0
    assert report.unchanged == 2
    assert report.disappeared == 0
    versions = conn.execute("SELECT COUNT(*) FROM product_version").fetchone()[0]
    assert versions == 2


def test_unchanged_record_still_advances_last_seen(tmp_path):
    conn = open_store(tmp_path / "s.db")
    sync(conn, recs(raw(1)), now="2026-08-01T00:00:00Z")
    sync(conn, recs(raw(1)), now="2026-08-05T00:00:00Z")
    last = conn.execute("SELECT last_seen FROM product_state WHERE product_id='1'").fetchone()[0]
    assert last == "2026-08-05T00:00:00Z"


def test_price_change_makes_a_version_but_no_enrichment_job(tmp_path):
    conn = open_store(tmp_path / "s.db")
    sync(conn, recs(raw(1, price="1299.00")), now="2026-08-01T00:00:00Z")
    report = sync(conn, recs(raw(1, price="999.00")), now="2026-08-02T00:00:00Z")
    assert (report.source_changed, report.enrichment_stale, report.enrichment_jobs) == (1, 0, 0)
    assert conn.execute("SELECT COUNT(*) FROM product_version").fetchone()[0] == 2


def test_title_change_makes_a_version_and_an_enrichment_job(tmp_path):
    conn = open_store(tmp_path / "s.db")
    sync(conn, recs(raw(1, title="Bomber Jacket")), now="2026-08-01T00:00:00Z")
    report = sync(conn, recs(raw(1, title="Bomber Jacket Navy")), now="2026-08-02T00:00:00Z")
    assert (report.source_changed, report.enrichment_stale, report.enrichment_jobs) == (0, 1, 1)


def test_disappearance_soft_deletes_and_keeps_every_row(tmp_path):
    conn = open_store(tmp_path / "s.db")
    sync(conn, recs(raw(1), raw(2)), now="2026-08-01T00:00:00Z")
    report = sync(conn, recs(raw(1)), now="2026-08-02T00:00:00Z")
    assert report.disappeared == 1
    assert current_live_count(conn) == 1
    row = conn.execute("SELECT deleted_at FROM product_state WHERE product_id='2'").fetchone()
    assert row[0] == "2026-08-02T00:00:00Z"
    assert conn.execute("SELECT COUNT(*) FROM product_state").fetchone()[0] == 2


def test_returning_product_is_undeleted(tmp_path):
    conn = open_store(tmp_path / "s.db")
    sync(conn, recs(raw(1), raw(2)), now="2026-08-01T00:00:00Z")
    sync(conn, recs(raw(1)), now="2026-08-02T00:00:00Z")
    sync(conn, recs(raw(1), raw(2)), now="2026-08-03T00:00:00Z")
    row = conn.execute("SELECT deleted_at FROM product_state WHERE product_id='2'").fetchone()
    assert row[0] is None


def test_reverting_after_completion_reuses_cached_enrichment(tmp_path):
    """A completed content hash is a result cache, not a permanently pending job."""
    conn = open_store(tmp_path / "s.db")
    sync(conn, recs(raw(1, title="A")), now="2026-08-01T00:00:00Z")
    hash_a = pending_enrichment(conn)[0][0]
    complete_enrichment(conn, hash_a, {"category": "jackets"}, "raw-a",
                        now="2026-08-01T01:00:00Z")
    sync(conn, recs(raw(1, title="B")), now="2026-08-02T00:00:00Z")
    hash_b = pending_enrichment(conn)[0][0]
    complete_enrichment(conn, hash_b, {"category": "jackets"}, "raw-b",
                        now="2026-08-02T01:00:00Z")
    report = sync(conn, recs(raw(1, title="A")), now="2026-08-03T00:00:00Z")
    assert report.enrichment_jobs == 0
    assert pending_enrichment(conn) == []


def test_sync_rolls_back_on_exception(tmp_path, monkeypatch):
    """Verify that sync rolls back all writes if an exception occurs mid-batch.
    Tests on a fresh connection to distinguish rollback from uncommitted transaction."""
    conn = open_store(tmp_path / "s.db")
    # First sync succeeds
    sync(conn, recs(raw(1)), now="2026-08-01T00:00:00Z")

    # Prepare a batch where we'll inject an error mid-process
    from catalog import store
    original_enqueue = store._enqueue
    call_count = [0]

    def failing_enqueue(conn_arg, pid, eih, rec, now):
        call_count[0] += 1
        if call_count[0] == 2:
            raise RuntimeError("Simulated enrichment error")
        return original_enqueue(conn_arg, pid, eih, rec, now)

    monkeypatch.setattr(store, "_enqueue", failing_enqueue)

    # Try to sync a batch that will fail partway through
    with pytest.raises(RuntimeError, match="Simulated enrichment error"):
        sync(conn, recs(raw(2), raw(3)), now="2026-08-02T00:00:00Z")

    # Open a fresh connection to verify nothing was written from the failed batch
    conn2 = sqlite3.connect(str(tmp_path / "s.db"))
    count = conn2.execute(
        "SELECT COUNT(*) FROM product_state WHERE product_id IN ('2', '3')"
    ).fetchone()[0]
    assert count == 0, "Failed batch should not be visible in fresh connection"
    # Also verify product_version has no rows from pids 2 or 3
    version_count = conn2.execute(
        "SELECT COUNT(*) FROM product_version WHERE product_id IN ('2', '3')"
    ).fetchone()[0]
    assert version_count == 0, "Failed batch versions should not be visible"
    conn2.close()
