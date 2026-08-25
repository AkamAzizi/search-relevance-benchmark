# Catalog Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest a Shopify fashion catalog politely and incrementally, so that running it twice produces zero new versions and zero enrichment jobs.

**Architecture:** A paced, disk-cached fetcher pulls `products.json` page by page. Each crawl is verified by running twice and comparing complete manifests — a crawl that cannot prove it saw a consistent catalog is discarded. Records are normalised and hashed twice: once over everything (version history) and once over search-relevant fields only (enrichment caching). State lives in SQLite; products are never hard-deleted.

**Tech Stack:** Python 3.13, `uv`, pytest, SQLite (stdlib), `curl` as HTTP transport.

**Spec:** `docs/superpowers/specs/2026-08-25-search-relevance-benchmark-design.md` (sections 4, 5, 6.1, 7)

## Global Constraints

- **Politeness (invariant 7):** minimum 3.0s between live requests; every response cached to disk; a bot-challenge response is NEVER cached as content.
- **User-Agent:** `SearchEvalResearch/0.1 (+search-relevance benchmarking; polite, cached)`. Never include a personal email address.
- **Imagery:** store image URLs only. Never download, never rehost.
- **Two hashes, never one:** `source_payload_hash` (everything except `updated_at`) and `enrichment_input_hash` (search-relevant fields only).
- **Soft-delete only.** A product absent from a crawl gets `deleted_at` set; its rows are never removed.
- **Anchor store:** `zoovillage.com`, ~2,000-2,250 products, native Shopify search.
- **Artifacts vs data:** `artifacts/` is committed; `data/` (raw snapshots, cache) is git-ignored.

**Deviation from the spec, flagged rather than silent:** the spec's pipeline diagram names `catalog.parquet`. This plan emits JSONL instead. At ~2,250 products parquet buys nothing and costs a dependency, and JSONL is diffable and inspectable. If catalogs ever grow past ~100k this should be revisited.

---

### Task 1: Project scaffolding and the polite fetcher

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `catalog/__init__.py`, `catalog/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PoliteFetcher(cache_dir: Path, delay: float = 3.0, transport: Callable[[str], bytes] | None = None, clock=time)` with `.get(url: str, namespace: str = "") -> bytes`; exceptions `Challenged`, `FetchError`.

- [ ] **Step 1: Create the project skeleton**

```bash
cd "/Users/akamazizi/Akam Azizi/rail"
mkdir -p catalog tests artifacts data
cat > pyproject.toml <<'EOF'
[project]
name = "search-relevance-benchmark"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = []

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
EOF
cat > .gitignore <<'EOF'
data/
__pycache__/
.venv/
.pytest_cache/
*.pyc
EOF
touch catalog/__init__.py
uv sync
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_fetch.py
import pytest
from catalog.fetch import PoliteFetcher, Challenged, FetchError


class FakeClock:
    def __init__(self): self.t, self.slept = 0.0, []
    def monotonic(self): return self.t
    def sleep(self, s): self.slept.append(s); self.t += s


def test_caches_response_and_does_not_refetch(tmp_path):
    calls = []
    def transport(url):
        calls.append(url)
        return b'{"products": []}'
    f = PoliteFetcher(tmp_path, delay=0.0, transport=transport, clock=FakeClock())
    assert f.get("https://x.test/a") == b'{"products": []}'
    assert f.get("https://x.test/a") == b'{"products": []}'
    assert calls == ["https://x.test/a"]


def test_challenge_raises_and_is_never_cached(tmp_path):
    def transport(url):
        return b"<html>Verifying your connection before you proceed</html>"
    f = PoliteFetcher(tmp_path, delay=0.0, transport=transport, clock=FakeClock())
    with pytest.raises(Challenged):
        f.get("https://x.test/b")
    assert list(tmp_path.glob("*.bin")) == []


def test_empty_body_raises_and_is_never_cached(tmp_path):
    f = PoliteFetcher(tmp_path, delay=0.0, transport=lambda u: b"", clock=FakeClock())
    with pytest.raises(FetchError):
        f.get("https://x.test/c")
    assert list(tmp_path.glob("*.bin")) == []


def test_paces_live_requests_but_not_cache_hits(tmp_path):
    clock = FakeClock()
    f = PoliteFetcher(tmp_path, delay=3.0, transport=lambda u: b"ok", clock=clock)
    f.get("https://x.test/1")
    f.get("https://x.test/2")
    f.get("https://x.test/1")          # cache hit, must not sleep
    assert clock.slept == [pytest.approx(3.0)]


def test_namespace_forces_a_fresh_fetch(tmp_path):
    calls = []
    def transport(url):
        calls.append(url)
        return b"ok"
    f = PoliteFetcher(tmp_path, delay=0.0, transport=transport, clock=FakeClock())
    f.get("https://x.test/p", namespace="run-a")
    f.get("https://x.test/p", namespace="run-a")   # cached within the namespace
    f.get("https://x.test/p", namespace="run-b")   # different namespace, refetched
    assert len(calls) == 2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.fetch'`

- [ ] **Step 4: Implement the fetcher**

```python
# catalog/fetch.py
"""Polite, cached HTTP for public storefront endpoints (invariant 7)."""
import hashlib
import subprocess
import time
from pathlib import Path
from typing import Callable

USER_AGENT = "SearchEvalResearch/0.1 (+search-relevance benchmarking; polite, cached)"
CHALLENGE_MARKERS = (b"Verifying your connection", b"cf-injected")


class Challenged(Exception):
    """The host served a bot challenge instead of content. Back off; never cache."""


class FetchError(Exception):
    """The transport failed or returned nothing."""


def curl_transport(url: str) -> bytes:
    result = subprocess.run(
        ["curl", "-sLg", "-m", "25", "-A", USER_AGENT,
         "-H", "Accept-Language: sv-SE,sv;q=0.9,en;q=0.5", url],
        capture_output=True,
    )
    if result.returncode != 0:
        raise FetchError(f"curl exit {result.returncode} for {url}")
    return result.stdout


class PoliteFetcher:
    """Caches every response to disk and never issues live requests faster than `delay`.

    `namespace` partitions the cache. Crawl verification passes a per-attempt namespace so
    the second crawl genuinely re-fetches rather than trivially matching the first from cache.
    """

    def __init__(self, cache_dir: Path, delay: float = 3.0,
                 transport: Callable[[str], bytes] | None = None, clock=time):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self._transport = transport or curl_transport
        self._clock = clock
        self._last = float("-inf")

    def _key(self, url: str, namespace: str) -> Path:
        digest = hashlib.sha256(f"{namespace}\x00{url}".encode()).hexdigest()[:20]
        return self.cache_dir / f"{digest}.bin"

    def get(self, url: str, namespace: str = "") -> bytes:
        key = self._key(url, namespace)
        if key.exists():
            return key.read_bytes()

        wait = self.delay - (self._clock.monotonic() - self._last)
        if wait > 0:
            self._clock.sleep(wait)
        self._last = self._clock.monotonic()

        body = self._transport(url)
        if any(marker in body for marker in CHALLENGE_MARKERS):
            raise Challenged(url)
        if not body:
            raise FetchError(url)

        key.write_bytes(body)
        return body
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetch.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore catalog/ tests/ uv.lock
git commit -m "feat(catalog): polite cached fetcher with challenge detection"
```

---

### Task 2: Record normalisation and the two hashes

**Files:**
- Create: `catalog/record.py`
- Test: `tests/test_record.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalize(raw: dict) -> dict`; `source_payload_hash(rec: dict) -> str`; `enrichment_input_hash(rec: dict) -> str`; constant `ENRICHMENT_FIELDS: tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_record.py
from catalog.record import (normalize, source_payload_hash,
                            enrichment_input_hash, ENRICHMENT_FIELDS)

RAW = {
    "id": 12345,
    "handle": "bomberjacka-svart",
    "title": "Bomber Jacket - Black",
    "body_html": "<p>En klassisk bomberjacka tillverkad i vattenavvisande material.</p>",
    "vendor": "Carhartt WIP",
    "product_type": "Jackor",
    "tags": ["Herr", "ytterplagg", "Jackor"],
    "updated_at": "2026-08-01T10:00:00Z",
    "options": [{"name": "Storlek"}],
    "variants": [{"title": "M", "price": "1299.00"}, {"title": "L", "price": "1299.00"}],
    "images": [{"src": "https://cdn.shopify.com/x/bomber.jpg"}],
}


def test_normalize_extracts_expected_shape():
    rec = normalize(RAW)
    assert rec["product_id"] == "12345"
    assert rec["vendor"] == "Carhartt WIP"
    assert rec["tags"] == ["Herr", "Jackor", "ytterplagg"]      # sorted for hash stability
    assert rec["variant_titles"] == ["M", "L"]
    assert rec["prices"] == ["1299.00", "1299.00"]
    assert rec["image_urls"] == ["https://cdn.shopify.com/x/bomber.jpg"]


def test_tag_order_does_not_change_any_hash():
    shuffled = dict(RAW, tags=["Jackor", "ytterplagg", "Herr"])
    a, b = normalize(RAW), normalize(shuffled)
    assert source_payload_hash(a) == source_payload_hash(b)
    assert enrichment_input_hash(a) == enrichment_input_hash(b)


def test_price_change_moves_source_hash_but_not_enrichment_hash():
    cheaper = dict(RAW, variants=[{"title": "M", "price": "999.00"},
                                  {"title": "L", "price": "999.00"}])
    a, b = normalize(RAW), normalize(cheaper)
    assert source_payload_hash(a) != source_payload_hash(b)
    assert enrichment_input_hash(a) == enrichment_input_hash(b)


def test_title_change_moves_both_hashes():
    retitled = dict(RAW, title="Bomber Jacket - Navy")
    a, b = normalize(RAW), normalize(retitled)
    assert source_payload_hash(a) != source_payload_hash(b)
    assert enrichment_input_hash(a) != enrichment_input_hash(b)


def test_updated_at_alone_moves_neither_hash():
    touched = dict(RAW, updated_at="2026-08-20T09:00:00Z")
    a, b = normalize(RAW), normalize(touched)
    assert source_payload_hash(a) == source_payload_hash(b)
    assert enrichment_input_hash(a) == enrichment_input_hash(b)


def test_enrichment_fields_are_a_strict_subset():
    rec = normalize(RAW)
    assert set(ENRICHMENT_FIELDS) < set(rec)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_record.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.record'`

- [ ] **Step 3: Implement**

```python
# catalog/record.py
"""Normalise Shopify products and hash them twice (spec 6.1).

Two hashes exist because one could not serve both purposes: excluding price kept
enrichment cheap but threw away source history.
"""
import hashlib
import json

# Search-relevant fields only. Drives enrichment caching, so price churn never re-pays
# for enrichment.
ENRICHMENT_FIELDS = (
    "title", "body_html", "tags", "vendor", "product_type", "options", "variant_titles",
)

# `updated_at` is metadata about when a change happened, not content. Including it would
# manufacture a new version every time Shopify touched a record for no substantive reason.
_SOURCE_EXCLUDED = ("updated_at",)


def normalize(raw: dict) -> dict:
    variants = raw.get("variants") or []
    return {
        "product_id": str(raw["id"]),
        "handle": raw.get("handle") or "",
        "title": raw.get("title") or "",
        "body_html": raw.get("body_html") or "",
        "vendor": raw.get("vendor") or "",
        "product_type": raw.get("product_type") or "",
        "tags": sorted(raw.get("tags") or []),
        "options": [o.get("name", "") for o in (raw.get("options") or [])],
        "variant_titles": [v.get("title", "") for v in variants],
        "prices": [v.get("price") for v in variants],
        # URLs only. Images are never downloaded or rehosted (invariant 7).
        "image_urls": [i.get("src", "") for i in (raw.get("images") or [])],
        "updated_at": raw.get("updated_at") or "",
    }


def _digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def source_payload_hash(rec: dict) -> str:
    return _digest({k: v for k, v in rec.items() if k not in _SOURCE_EXCLUDED})


def enrichment_input_hash(rec: dict) -> str:
    return _digest({k: rec[k] for k in ENRICHMENT_FIELDS})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_record.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add catalog/record.py tests/test_record.py
git commit -m "feat(catalog): normalise records and split source from enrichment hash"
```

---

### Task 3: Paginated crawl with a verifiable manifest

**Files:**
- Create: `catalog/shopify.py`
- Test: `tests/test_shopify.py`

**Interfaces:**
- Consumes: `PoliteFetcher` (Task 1), `normalize` (Task 2).
- Produces: `crawl_once(fetcher, domain: str, namespace: str, max_pages: int = 60) -> list[dict]`; `build_manifest(records: list[dict]) -> dict` returning `{"count": int, "digest": str}`; exception `InconsistentCrawl`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_shopify.py
import json
import pytest
from catalog.fetch import PoliteFetcher
from catalog.shopify import crawl_once, build_manifest, InconsistentCrawl


class FakeClock:
    def __init__(self): self.t = 0.0
    def monotonic(self): return self.t
    def sleep(self, s): self.t += s


def product(pid, title="T"):
    return {"id": pid, "handle": f"h{pid}", "title": title, "body_html": "",
            "vendor": "V", "product_type": "P", "tags": [], "options": [],
            "variants": [{"title": "M", "price": "10.00"}], "images": [],
            "updated_at": "2026-01-01T00:00:00Z"}


def pages_transport(pages):
    """pages: dict of page-number -> list of raw products."""
    def transport(url):
        n = int(url.split("page=")[1])
        return json.dumps({"products": pages.get(n, [])}).encode()
    return transport


def test_crawl_walks_pages_until_empty(tmp_path):
    pages = {1: [product(1), product(2)], 2: [product(3)], 3: []}
    f = PoliteFetcher(tmp_path, delay=0.0, transport=pages_transport(pages), clock=FakeClock())
    records = crawl_once(f, "shop.test", namespace="run-1")
    assert [r["product_id"] for r in records] == ["1", "2", "3"]


def test_manifest_digest_is_order_independent():
    a = build_manifest([{"product_id": "1"}, {"product_id": "2"}])
    b = build_manifest([{"product_id": "2"}, {"product_id": "1"}])
    assert a["digest"] == b["digest"]
    assert a["count"] == 2


def test_duplicate_ids_across_pages_are_rejected():
    with pytest.raises(InconsistentCrawl, match="duplicate"):
        build_manifest([{"product_id": "1"}, {"product_id": "1"}])


def test_manifest_differs_when_catalog_differs():
    a = build_manifest([{"product_id": "1"}, {"product_id": "2"}])
    b = build_manifest([{"product_id": "1"}, {"product_id": "3"}])
    assert a["digest"] != b["digest"]


def test_max_pages_guard_stops_a_runaway_crawl(tmp_path):
    endless = lambda url: json.dumps({"products": [product(1)]}).encode()
    f = PoliteFetcher(tmp_path, delay=0.0, transport=endless, clock=FakeClock())
    with pytest.raises(InconsistentCrawl, match="max_pages"):
        crawl_once(f, "shop.test", namespace="run-1", max_pages=3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_shopify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.shopify'`

- [ ] **Step 3: Implement**

```python
# catalog/shopify.py
"""Walk Shopify's public products.json and prove the crawl was self-consistent."""
import hashlib
import json
from collections import Counter

from catalog.record import normalize

PAGE_SIZE = 250


class InconsistentCrawl(Exception):
    """The crawl cannot prove it saw a consistent catalog. Discard it."""


def crawl_once(fetcher, domain: str, namespace: str, max_pages: int = 60) -> list[dict]:
    records: list[dict] = []
    for page in range(1, max_pages + 1):
        url = f"https://{domain}/products.json?limit={PAGE_SIZE}&page={page}"
        batch = json.loads(fetcher.get(url, namespace=namespace))["products"]
        if not batch:
            return records
        records.extend(normalize(raw) for raw in batch)
    raise InconsistentCrawl(
        f"{domain}: still returning products at max_pages={max_pages}; raise the limit "
        f"or investigate before trusting this crawl"
    )


def build_manifest(records: list[dict]) -> dict:
    ids = [r["product_id"] for r in records]
    duplicates = [pid for pid, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise InconsistentCrawl(
            f"duplicate ids across pages: {duplicates[:5]} "
            f"({len(duplicates)} total) - pagination shifted mid-crawl"
        )
    joined = "\n".join(sorted(ids))
    return {"count": len(ids), "digest": hashlib.sha256(joined.encode()).hexdigest()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_shopify.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add catalog/shopify.py tests/test_shopify.py
git commit -m "feat(catalog): paginated crawl with duplicate-id detection and manifest digest"
```

---

### Task 4: Whole-crawl consistency verification

**Files:**
- Modify: `catalog/shopify.py`
- Test: `tests/test_shopify.py`

**Interfaces:**
- Consumes: `crawl_once`, `build_manifest` (Task 3).
- Produces: `crawl_verified(fetcher, domain: str, run_id: str, max_pages: int = 60) -> tuple[list[dict], dict]` — returns records plus the agreed manifest, or raises `InconsistentCrawl`.

Re-fetching page 1 proves only that page 1 is stable. Two complete crawls are what the spec requires, and the fetcher's `namespace` is what makes the second one genuinely fresh rather than a cache replay.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_shopify.py
from catalog.shopify import crawl_verified


def test_verified_crawl_accepts_two_matching_crawls(tmp_path):
    pages = {1: [product(1), product(2)], 2: []}
    f = PoliteFetcher(tmp_path, delay=0.0, transport=pages_transport(pages), clock=FakeClock())
    records, manifest = crawl_verified(f, "shop.test", run_id="r1")
    assert manifest["count"] == 2
    assert [r["product_id"] for r in records] == ["1", "2"]


def test_verified_crawl_rejects_a_catalog_that_changed_mid_run(tmp_path):
    state = {"calls": 0}
    def shifting_transport(url):
        n = int(url.split("page=")[1])
        if n != 1:
            return json.dumps({"products": []}).encode()
        state["calls"] += 1
        # a product appears between the first and second crawl
        items = [product(1)] if state["calls"] == 1 else [product(1), product(2)]
        return json.dumps({"products": items}).encode()

    f = PoliteFetcher(tmp_path, delay=0.0, transport=shifting_transport, clock=FakeClock())
    with pytest.raises(InconsistentCrawl, match="changed between crawls"):
        crawl_verified(f, "shop.test", run_id="r1")


def test_verification_crawls_use_different_cache_namespaces(tmp_path):
    seen = []
    def counting_transport(url):
        seen.append(url)
        n = int(url.split("page=")[1])
        return json.dumps({"products": [product(1)] if n == 1 else []}).encode()
    f = PoliteFetcher(tmp_path, delay=0.0, transport=counting_transport, clock=FakeClock())
    crawl_verified(f, "shop.test", run_id="r1")
    # page 1 and page 2 fetched twice - once per verification crawl, not served from cache
    assert len(seen) == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_shopify.py -v`
Expected: FAIL — `ImportError: cannot import name 'crawl_verified'`

- [ ] **Step 3: Implement**

```python
# append to catalog/shopify.py

def crawl_verified(fetcher, domain: str, run_id: str,
                   max_pages: int = 60) -> tuple[list[dict], dict]:
    """Crawl twice and require both manifests to agree.

    Page-based pagination is unstable under concurrent catalog edits and the public
    endpoint offers no `since_id`, so consistency is detected rather than prevented.
    A crawl that cannot prove consistency must not become a benchmark.
    """
    first = crawl_once(fetcher, domain, namespace=f"{run_id}-a", max_pages=max_pages)
    first_manifest = build_manifest(first)

    second = crawl_once(fetcher, domain, namespace=f"{run_id}-b", max_pages=max_pages)
    second_manifest = build_manifest(second)

    if first_manifest["digest"] != second_manifest["digest"]:
        raise InconsistentCrawl(
            f"{domain}: catalog changed between crawls "
            f"({first_manifest['count']} then {second_manifest['count']} products). "
            f"Discard and re-crawl."
        )
    return second, second_manifest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_shopify.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add catalog/shopify.py tests/test_shopify.py
git commit -m "feat(catalog): verify crawls by comparing two complete manifests"
```

---

### Task 5: SQLite state store and sync transitions

**Files:**
- Create: `catalog/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `source_payload_hash`, `enrichment_input_hash` (Task 2).
- Produces: `open_store(path) -> sqlite3.Connection`; `sync(conn, records: list[dict], now: str) -> SyncReport`; dataclass `SyncReport(new, source_changed, enrichment_stale, unchanged, disappeared, enrichment_jobs)`; `pending_enrichment(conn) -> list[tuple[str, str]]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store.py
from catalog.record import normalize
from catalog.store import open_store, sync, pending_enrichment


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
    report = sync(conn, recs(raw(1), raw(2)), now="2026-08-01T00:00:00Z")
    assert (report.new, report.unchanged, report.enrichment_jobs) == (2, 0, 2)
    assert len(pending_enrichment(conn)) == 2


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


def test_reverting_a_change_does_not_re_enqueue_enrichment(tmp_path):
    """Enrichment is keyed by content hash, so a revert reuses the existing job."""
    conn = open_store(tmp_path / "s.db")
    sync(conn, recs(raw(1, title="A")), now="2026-08-01T00:00:00Z")
    sync(conn, recs(raw(1, title="B")), now="2026-08-02T00:00:00Z")
    report = sync(conn, recs(raw(1, title="A")), now="2026-08-03T00:00:00Z")
    assert report.enrichment_jobs == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.store'`

- [ ] **Step 3: Implement**

```python
# catalog/store.py
"""Incremental catalog state (spec 6.1). Products are never hard-deleted."""
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from catalog.record import enrichment_input_hash, source_payload_hash

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
CREATE TABLE IF NOT EXISTS enrichment_job (
    product_id            TEXT NOT NULL,
    enrichment_input_hash TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    PRIMARY KEY (product_id, enrichment_input_hash)
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


def _enqueue(conn, pid, eih, now) -> bool:
    """Returns True only if this is a genuinely new enrichment job."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO enrichment_job VALUES (?,?,?)", (pid, eih, now)
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
            report.enrichment_jobs += int(_enqueue(conn, pid, eih, now))
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
            report.enrichment_jobs += int(_enqueue(conn, pid, eih, now))
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
        "SELECT product_id, enrichment_input_hash FROM enrichment_job ORDER BY product_id"
    ).fetchall()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add catalog/store.py tests/test_store.py
git commit -m "feat(catalog): sqlite state store with two-hash sync transitions"
```

---

### Task 6: Ingest orchestration, snapshot artifact, and CLI

**Files:**
- Create: `catalog/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `ingest(domain, data_dir, run_id, artifacts_dir=None, fetcher=None, now=None) -> IngestResult`; dataclass `IngestResult(domain, run_id, manifest, report, snapshot_path)`; CLI `python -m catalog.ingest --store <domain>`.

Writes `data/<domain>/snapshot-<run_id>.jsonl` (git-ignored, retained privately) and `artifacts/<domain>/manifest-<run_id>.json` (committed — the manifest is ours, the catalog is theirs).

**`artifacts_dir` is deliberately NOT under `data_dir`.** `data/` is git-ignored; writing manifests beneath it would git-ignore the very artifacts that make the snapshot auditable.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ingest.py
import json
from catalog.fetch import PoliteFetcher
from catalog.ingest import ingest


class FakeClock:
    def __init__(self): self.t = 0.0
    def monotonic(self): return self.t
    def sleep(self, s): self.t += s


def product(pid):
    return {"id": pid, "handle": f"h{pid}", "title": f"Jacket {pid}",
            "body_html": "<p>bomberjacka</p>", "vendor": "V", "product_type": "Jackor",
            "tags": ["Herr"], "options": [], "images": [],
            "variants": [{"title": "M", "price": "10.00"}],
            "updated_at": "2026-01-01T00:00:00Z"}


def transport_for(items):
    def transport(url):
        n = int(url.split("page=")[1])
        return json.dumps({"products": items if n == 1 else []}).encode()
    return transport


def test_ingest_writes_snapshot_and_manifest(tmp_path):
    f = PoliteFetcher(tmp_path / "cache", delay=0.0,
                      transport=transport_for([product(1), product(2)]), clock=FakeClock())
    artifacts = tmp_path / "artifacts"
    result = ingest("shop.test", tmp_path, run_id="r1", artifacts_dir=artifacts,
                    fetcher=f, now="2026-08-01T00:00:00Z")
    assert result.manifest["count"] == 2
    assert result.report.new == 2
    lines = result.snapshot_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["product_id"] == "1"
    manifest_file = artifacts / "shop.test" / "manifest-r1.json"
    assert json.loads(manifest_file.read_text())["digest"] == result.manifest["digest"]


def test_manifest_is_not_written_under_the_gitignored_data_dir(tmp_path):
    f = PoliteFetcher(tmp_path / "cache", delay=0.0,
                      transport=transport_for([product(1)]), clock=FakeClock())
    ingest("shop.test", tmp_path / "data", run_id="r1",
           artifacts_dir=tmp_path / "artifacts", fetcher=f, now="2026-08-01T00:00:00Z")
    assert not list((tmp_path / "data").rglob("manifest-*.json"))
    assert (tmp_path / "artifacts" / "shop.test" / "manifest-r1.json").exists()


def test_running_ingest_twice_produces_no_new_versions_or_jobs(tmp_path):
    """End-to-end form of the spec 6.1 acceptance test."""
    items = [product(1), product(2)]
    mk = lambda: PoliteFetcher(tmp_path / "cache", delay=0.0,
                               transport=transport_for(items), clock=FakeClock())
    art = tmp_path / "artifacts"
    ingest("shop.test", tmp_path, run_id="r1", artifacts_dir=art,
           fetcher=mk(), now="2026-08-01T00:00:00Z")
    second = ingest("shop.test", tmp_path, run_id="r2", artifacts_dir=art,
                    fetcher=mk(), now="2026-08-02T00:00:00Z")
    assert second.report.new == 0
    assert second.report.source_changed == 0
    assert second.report.enrichment_stale == 0
    assert second.report.enrichment_jobs == 0
    assert second.report.unchanged == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'catalog.ingest'`

- [ ] **Step 3: Implement**

```python
# catalog/ingest.py
"""Orchestrate a verified crawl into versioned state plus a snapshot artifact."""
import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from catalog.fetch import PoliteFetcher
from catalog.shopify import crawl_verified
from catalog.store import SyncReport, open_store, sync


@dataclass
class IngestResult:
    domain: str
    run_id: str
    manifest: dict
    report: SyncReport
    snapshot_path: Path


def ingest(domain: str, data_dir: Path, run_id: str,
           artifacts_dir: Path | None = None,
           fetcher: PoliteFetcher | None = None, now: str | None = None) -> IngestResult:
    data_dir = Path(data_dir)
    # NOT under data_dir: data/ is git-ignored, and manifests must be committable.
    artifacts_dir = Path(artifacts_dir) if artifacts_dir else Path("artifacts")
    now = now or datetime.now(UTC).isoformat()
    fetcher = fetcher or PoliteFetcher(data_dir / "cache")

    records, manifest = crawl_verified(fetcher, domain, run_id=run_id)

    store_dir = data_dir / domain
    store_dir.mkdir(parents=True, exist_ok=True)
    conn = open_store(store_dir / "catalog.db")
    report = sync(conn, records, now=now)

    # Raw snapshot: retained privately, never republished (invariant 7).
    snapshot_path = store_dir / f"snapshot-{run_id}.jsonl"
    with snapshot_path.open("w", encoding="utf-8") as handle:
        for rec in sorted(records, key=lambda r: r["product_id"]):
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Manifest: ours, and committed, so a reader can verify a snapshot they hold.
    artifact_dir = artifacts_dir / domain
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / f"manifest-{run_id}.json").write_text(
        json.dumps({**manifest, "domain": domain, "run_id": run_id, "crawled_at": now},
                   indent=2) + "\n",
        encoding="utf-8",
    )
    return IngestResult(domain, run_id, manifest, report, snapshot_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a Shopify catalog, politely.")
    parser.add_argument("--store", required=True, help="e.g. zoovillage.com")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--artifacts-dir", default="artifacts")
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()

    result = ingest(args.store, Path(args.data_dir), run_id=args.run_id,
                    artifacts_dir=Path(args.artifacts_dir))
    r = result.report
    print(f"{result.domain}  run={result.run_id}  products={result.manifest['count']}")
    print(f"  new={r.new} source_changed={r.source_changed} "
          f"enrichment_stale={r.enrichment_stale} unchanged={r.unchanged} "
          f"disappeared={r.disappeared}")
    print(f"  enrichment jobs queued: {r.enrichment_jobs}")
    print(f"  snapshot: {result.snapshot_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ingest.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -v`
Expected: 30 passed

- [ ] **Step 6: Commit**

```bash
git add catalog/ingest.py tests/test_ingest.py
git commit -m "feat(catalog): ingest orchestration with snapshot and manifest artifacts"
```

---

### Task 7: Ingest the real anchor catalog

**Files:**
- Modify: `.gitignore` (confirm `data/` is ignored), `artifacts/` (new committed manifests)

**Interfaces:**
- Consumes: the CLI from Task 6.
- Produces: a real snapshot of `zoovillage.com` and its committed manifest; the exact catalog size, which the spec currently records only as a 2,000-2,250 bound.

This is the first live run. It takes roughly 2 × 10 pages × 3s ≈ 60s plus latency, because verification crawls twice.

- [ ] **Step 1: Ingest the anchor**

```bash
cd "/Users/akamazizi/Akam Azizi/rail"
uv run python -m catalog.ingest --store zoovillage.com --run-id anchor-001
```

Expected: `products=` a number between 2000 and 2250; `new=` that same number; `enrichment jobs queued=` that same number.

If it raises `InconsistentCrawl: catalog changed between crawls`, that is the check working. Wait a few minutes and re-run — a live storefront can legitimately change mid-crawl.

If it raises `Challenged`, back off for several hours. Do not reduce the delay.

- [ ] **Step 2: Verify idempotency against the live catalog**

```bash
uv run python -m catalog.ingest --store zoovillage.com --run-id anchor-002
```

Expected: `new=0 source_changed=0 enrichment_stale=0 unchanged=<same count> disappeared=0`, and `enrichment jobs queued: 0`.

Small non-zero `source_changed` is plausible if prices moved between runs; `enrichment_stale` should be 0. If `enrichment_stale` is non-zero, the enrichment hash is picking up a volatile field — investigate before proceeding.

- [ ] **Step 3: Record the real catalog size in the spec**

Update section 4's product count for `zoovillage.com` from `~2,000-2,250` to the exact figure, and remove the corresponding bullet from section 10 Open questions.

- [ ] **Step 4: Commit the manifest and the spec correction**

```bash
git add artifacts/ docs/superpowers/specs/2026-08-25-search-relevance-benchmark-design.md
git commit -m "chore(catalog): anchor snapshot manifest and exact catalog size"
```

- [ ] **Step 5: Ingest storefronts 2 and 3**

```bash
uv run python -m catalog.ingest --store rezetstore.dk   --run-id sf2-001
uv run python -m catalog.ingest --store galvingreen.com --run-id sf3-001
git add artifacts/ && git commit -m "chore(catalog): storefront 2 and 3 manifests"
```

---

## Verification

The pipeline is done when all of these hold:

1. `uv run pytest -v` — 30 passed.
2. `uv run python -m catalog.ingest --store zoovillage.com --run-id vN` twice in succession reports `new=0`, `enrichment_stale=0`, `enrichment_jobs=0` on the second run. **This is the claim the component exists to support.**
3. `data/zoovillage.com/snapshot-anchor-001.jsonl` has one line per product, sorted by id.
4. `artifacts/zoovillage.com/manifest-anchor-001.json` is committed; `data/` is not.
5. `sqlite3 data/zoovillage.com/catalog.db "SELECT COUNT(*) FROM product_state WHERE deleted_at IS NULL"` matches the manifest count.
6. No image bytes anywhere under `data/` — only URLs inside the JSONL.

## Sequencing constraint discovered during review

Spec section 5 requires `NativeSearch` to be captured **as close to crawl time as possible**,
because the storefront's internal index drifts away from our snapshot. That capture needs the
query set, which is checkpoint 1 and is human work not yet done. So there is an ordering
constraint this plan cannot satisfy alone:

> **Re-run `catalog.ingest` immediately before capturing native search responses**, with a
> fresh `run_id`, and use *that* snapshot as the benchmark snapshot.

The anchor ingest in Task 7 exists to prove the pipeline works and to fix the exact catalog
size. It is not automatically the snapshot the benchmark runs against. Re-ingesting costs
~40 requests and removes any drift between snapshot and baseline; skipping it would reopen
finding #4 by the back door. The capture step itself lives in the evaluation plan, which
consumes `crawl_verified` and `PoliteFetcher` from here.

## What this plan deliberately does not do

Enrichment, retrieval, evaluation and the service are separate plans. This one ends with a
trustworthy, re-runnable snapshot and a queue of enrichment jobs waiting to be consumed.
