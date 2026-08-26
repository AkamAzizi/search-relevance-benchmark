import json
import hashlib

import pytest

from catalog.fetch import PoliteFetcher, RequestProfile
from catalog.ingest import ArtifactExists, ingest
from catalog.shopify import InconsistentCrawl
from catalog.store import current_live_count, open_store

SV = RequestProfile("sv-SE", "sv-SE,sv;q=0.9,en;q=0.5")


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
    def transport(url, profile):
        n = int(url.split("page=")[1])
        return json.dumps({"products": items if n == 1 else []}).encode()
    return transport


def test_ingest_writes_snapshot_and_manifest(tmp_path):
    f = PoliteFetcher(tmp_path / "cache", SV, delay=0.0,
                      transport=transport_for([product(1), product(2)]), clock=FakeClock())
    artifacts = tmp_path / "artifacts"
    result = ingest("shop.test", tmp_path / "data", run_id="r1", profile=SV,
                    artifacts_dir=artifacts, fetcher=f,
                    now="2026-08-01T00:00:00Z", attempt_id="a1")
    assert result.manifest["count"] == 2
    assert result.report.new == 2
    lines = result.snapshot_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["product_id"] == "1"
    manifest_file = artifacts / "shop.test" / "manifest-r1.json"
    committed = json.loads(manifest_file.read_text())
    assert committed["digest"] == result.manifest["digest"]
    assert committed["snapshot_sha256"] == hashlib.sha256(
        result.snapshot_path.read_bytes()
    ).hexdigest()
    assert committed["request_profile"] == {
        "locale": "sv-SE", "accept_language": "sv-SE,sv;q=0.9,en;q=0.5"
    }


def test_manifest_is_not_written_under_the_gitignored_data_dir(tmp_path):
    f = PoliteFetcher(tmp_path / "cache", SV, delay=0.0,
                      transport=transport_for([product(1)]), clock=FakeClock())
    ingest("shop.test", tmp_path / "data", run_id="r1", profile=SV,
           artifacts_dir=tmp_path / "artifacts", fetcher=f,
           now="2026-08-01T00:00:00Z", attempt_id="a1")
    assert not list((tmp_path / "data").rglob("manifest-*.json"))
    assert (tmp_path / "artifacts" / "shop.test" / "manifest-r1.json").exists()


def test_running_ingest_twice_produces_no_new_versions_or_jobs(tmp_path):
    """End-to-end form of the spec 6.1 acceptance test."""
    items = [product(1), product(2)]
    mk = lambda: PoliteFetcher(tmp_path / "cache", SV, delay=0.0,
                               transport=transport_for(items), clock=FakeClock())
    art = tmp_path / "artifacts"
    ingest("shop.test", tmp_path / "data", run_id="r1", profile=SV,
           artifacts_dir=art, fetcher=mk(), now="2026-08-01T00:00:00Z",
           attempt_id="a1")
    second = ingest("shop.test", tmp_path / "data", run_id="r2", profile=SV,
                    artifacts_dir=art, fetcher=mk(), now="2026-08-02T00:00:00Z",
                    attempt_id="a2")
    assert second.report.new == 0
    assert second.report.source_changed == 0
    assert second.report.enrichment_stale == 0
    assert second.report.enrichment_jobs == 0
    assert second.report.unchanged == 2


def test_successful_run_id_is_immutable(tmp_path):
    items = [product(1)]
    f = PoliteFetcher(tmp_path / "cache", SV, delay=0.0,
                      transport=transport_for(items), clock=FakeClock())
    kwargs = dict(domain="shop.test", data_dir=tmp_path / "data", run_id="r1",
                  profile=SV, artifacts_dir=tmp_path / "artifacts",
                  now="2026-08-01T00:00:00Z")
    ingest(**kwargs, fetcher=f, attempt_id="a1")
    with pytest.raises(ArtifactExists, match="r1"):
        ingest(**kwargs, fetcher=f, attempt_id="a2")


def test_failed_attempt_can_retry_same_run_id_with_fresh_attempt_cache(tmp_path):
    state = {"page_1_calls": 0}
    def shifting(url, profile):
        page = int(url.split("page=")[1])
        if page != 1:
            return b'{"products":[]}'
        state["page_1_calls"] += 1
        items = [product(1)] if state["page_1_calls"] == 1 else [product(1), product(2)]
        return json.dumps({"products": items}).encode()

    first = PoliteFetcher(tmp_path / "cache", SV, delay=0.0,
                          transport=shifting, clock=FakeClock())
    kwargs = dict(domain="shop.test", data_dir=tmp_path / "data", run_id="r1",
                  profile=SV, artifacts_dir=tmp_path / "artifacts",
                  now="2026-08-01T00:00:00Z")
    with pytest.raises(InconsistentCrawl):
        ingest(**kwargs, fetcher=first, attempt_id="failed-attempt")

    stable = PoliteFetcher(tmp_path / "cache", SV, delay=0.0,
                           transport=transport_for([product(1), product(2)]),
                           clock=FakeClock())
    result = ingest(**kwargs, fetcher=stable, attempt_id="fresh-attempt")
    assert result.manifest["count"] == 2


def test_rejected_large_drop_does_not_mutate_store(tmp_path):
    art = tmp_path / "artifacts"
    data = tmp_path / "data"
    first_items = [product(i) for i in range(10)]
    first = PoliteFetcher(tmp_path / "cache", SV, delay=0.0,
                          transport=transport_for(first_items), clock=FakeClock())
    ingest("shop.test", data, "r1", SV, artifacts_dir=art, fetcher=first,
           now="2026-08-01T00:00:00Z", attempt_id="a1")

    second = PoliteFetcher(tmp_path / "cache", SV, delay=0.0,
                           transport=transport_for([product(1), product(2)]),
                           clock=FakeClock())
    with pytest.raises(InconsistentCrawl, match="large catalog drop"):
        ingest("shop.test", data, "r2", SV, artifacts_dir=art, fetcher=second,
               now="2026-08-02T00:00:00Z", attempt_id="a2")
    assert current_live_count(open_store(data / "shop.test" / "catalog.db")) == 10
