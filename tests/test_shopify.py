import json
import pytest
from catalog.fetch import PoliteFetcher, RequestProfile
from catalog.shopify import crawl_once, build_manifest, InconsistentCrawl, crawl_verified

SV = RequestProfile("sv-SE", "sv-SE,sv;q=0.9,en;q=0.5")


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
    def transport(url, profile):
        n = int(url.split("page=")[1])
        return json.dumps({"products": pages.get(n, [])}).encode()
    return transport


def test_crawl_walks_pages_until_empty(tmp_path):
    pages = {1: [product(1), product(2)], 2: [product(3)], 3: []}
    f = PoliteFetcher(tmp_path, SV, delay=0.0,
                      transport=pages_transport(pages), clock=FakeClock())
    records = crawl_once(f, "shop.test", namespace="run-1")
    assert [r["product_id"] for r in records] == ["1", "2", "3"]


def test_manifest_digest_is_order_independent():
    from catalog.record import normalize
    a = build_manifest([normalize(product(1)), normalize(product(2))])
    b = build_manifest([normalize(product(2)), normalize(product(1))])
    assert a["digest"] == b["digest"]
    assert a["count"] == 2


def test_duplicate_ids_across_pages_are_rejected():
    from catalog.record import normalize
    with pytest.raises(InconsistentCrawl, match="duplicate"):
        build_manifest([normalize(product(1)), normalize(product(1))])


def test_manifest_differs_when_catalog_differs():
    from catalog.record import normalize
    a = build_manifest([normalize(product(1)), normalize(product(2))])
    b = build_manifest([normalize(product(1)), normalize(product(3))])
    assert a["digest"] != b["digest"]


def test_manifest_differs_when_same_id_has_changed_content():
    from catalog.record import normalize
    a = build_manifest([normalize(product(1, title="Black Jacket"))])
    b = build_manifest([normalize(product(1, title="Navy Jacket"))])
    assert a["digest"] != b["digest"]


def test_invalid_catalog_shape_is_rejected_before_cache(tmp_path):
    f = PoliteFetcher(
        tmp_path, SV, delay=0.0,
        transport=lambda url, profile: b'{"message":"temporary queue"}',
        clock=FakeClock(),
    )
    with pytest.raises(InconsistentCrawl, match="products list"):
        crawl_once(f, "shop.test", namespace="run-1")
    assert list(tmp_path.glob("*.bin")) == []


def test_max_pages_guard_stops_a_runaway_crawl(tmp_path):
    endless = lambda url, profile: json.dumps({"products": [product(1)]}).encode()
    f = PoliteFetcher(tmp_path, SV, delay=0.0, transport=endless, clock=FakeClock())
    with pytest.raises(InconsistentCrawl, match="max_pages"):
        crawl_once(f, "shop.test", namespace="run-1", max_pages=3)


def test_element_malformed_product_is_rejected_before_cache(tmp_path):
    f = PoliteFetcher(
        tmp_path, SV, delay=0.0,
        transport=lambda url, profile: b'{"products": [{"title": "no id here"}]}',
        clock=FakeClock(),
    )
    with pytest.raises(InconsistentCrawl, match="product element"):
        crawl_once(f, "shop.test", namespace="run-1")
    assert list(tmp_path.glob("*.bin")) == []


def test_element_malformed_variants_is_rejected_before_cache(tmp_path):
    body = b'{"products": [{"id": 1, "variants": {"not": "a list"}}]}'
    f = PoliteFetcher(
        tmp_path, SV, delay=0.0,
        transport=lambda url, profile: body,
        clock=FakeClock(),
    )
    with pytest.raises(InconsistentCrawl, match="variants"):
        crawl_once(f, "shop.test", namespace="run-1")
    assert list(tmp_path.glob("*.bin")) == []


def test_element_malformed_options_is_rejected_before_cache(tmp_path):
    body = b'{"products": [{"id": 1, "options": ["Size", "Color"]}]}'
    f = PoliteFetcher(
        tmp_path, SV, delay=0.0,
        transport=lambda url, profile: body,
        clock=FakeClock(),
    )
    with pytest.raises(InconsistentCrawl, match="options"):
        crawl_once(f, "shop.test", namespace="run-1")
    assert list(tmp_path.glob("*.bin")) == []


def test_element_malformed_images_is_rejected_before_cache(tmp_path):
    body = b'{"products": [{"id": 1, "images": ["https://x/a.jpg"]}]}'
    f = PoliteFetcher(
        tmp_path, SV, delay=0.0,
        transport=lambda url, profile: body,
        clock=FakeClock(),
    )
    with pytest.raises(InconsistentCrawl, match="images"):
        crawl_once(f, "shop.test", namespace="run-1")
    assert list(tmp_path.glob("*.bin")) == []


def test_verified_crawl_accepts_two_matching_crawls(tmp_path):
    pages = {1: [product(1), product(2)], 2: []}
    f = PoliteFetcher(tmp_path, SV, delay=0.0,
                      transport=pages_transport(pages), clock=FakeClock())
    records, manifest = crawl_verified(f, "shop.test", attempt_id="a1")
    assert manifest["count"] == 2
    assert [r["product_id"] for r in records] == ["1", "2"]


def test_verified_crawl_rejects_a_catalog_that_changed_mid_run(tmp_path):
    state = {"calls": 0}
    def shifting_transport(url, profile):
        n = int(url.split("page=")[1])
        if n != 1:
            return json.dumps({"products": []}).encode()
        state["calls"] += 1
        # a product appears between the first and second crawl
        items = [product(1)] if state["calls"] == 1 else [product(1), product(2)]
        return json.dumps({"products": items}).encode()

    f = PoliteFetcher(tmp_path, SV, delay=0.0,
                      transport=shifting_transport, clock=FakeClock())
    with pytest.raises(InconsistentCrawl, match="changed between crawls"):
        crawl_verified(f, "shop.test", attempt_id="a1")


def test_digest_mismatch_message_reports_differing_content_ids(tmp_path):
    state = {"calls": 0}
    def shifting_title_transport(url, profile):
        n = int(url.split("page=")[1])
        if n != 1:
            return json.dumps({"products": []}).encode()
        state["calls"] += 1
        # same id on both crawls, but its content changed - the case the two plain
        # counts cannot distinguish from an id actually appearing or disappearing
        title = "Black Jacket" if state["calls"] == 1 else "Navy Jacket"
        return json.dumps({"products": [product(1, title=title)]}).encode()

    f = PoliteFetcher(tmp_path, SV, delay=0.0,
                      transport=shifting_title_transport, clock=FakeClock())
    with pytest.raises(InconsistentCrawl) as exc_info:
        crawl_verified(f, "shop.test", attempt_id="a1")
    message = str(exc_info.value)
    assert "0 id(s) only in the first crawl" in message
    assert "0 only in the second" in message
    assert "1 present in both with differing content" in message
    assert "e.g. 1" in message


def test_verification_crawls_use_different_cache_namespaces(tmp_path):
    seen = []
    def counting_transport(url, profile):
        seen.append(url)
        n = int(url.split("page=")[1])
        return json.dumps({"products": [product(1)] if n == 1 else []}).encode()
    f = PoliteFetcher(tmp_path, SV, delay=0.0,
                      transport=counting_transport, clock=FakeClock())
    crawl_verified(f, "shop.test", attempt_id="a1")
    # page 1 and page 2 fetched twice - once per verification crawl, not served from cache
    assert len(seen) == 4


def test_verified_crawl_rejects_two_matching_empty_crawls(tmp_path):
    f = PoliteFetcher(tmp_path, SV, delay=0.0,
                      transport=pages_transport({1: []}), clock=FakeClock())
    with pytest.raises(InconsistentCrawl, match="minimum_count=1"):
        crawl_verified(f, "shop.test", attempt_id="a1")


def test_verified_crawl_rejects_suspicious_drop_before_sync(tmp_path):
    pages = {1: [product(1), product(2)], 2: []}
    f = PoliteFetcher(tmp_path, SV, delay=0.0,
                      transport=pages_transport(pages), clock=FakeClock())
    with pytest.raises(InconsistentCrawl, match="large catalog drop"):
        crawl_verified(f, "shop.test", attempt_id="a1", previous_count=10,
                       max_drop_fraction=0.10)


def test_large_drop_requires_explicit_override(tmp_path):
    pages = {1: [product(1), product(2)], 2: []}
    f = PoliteFetcher(tmp_path, SV, delay=0.0,
                      transport=pages_transport(pages), clock=FakeClock())
    records, manifest = crawl_verified(
        f, "shop.test", attempt_id="a1", previous_count=10,
        max_drop_fraction=0.10, allow_large_drop=True,
    )
    assert len(records) == manifest["count"] == 2


def test_drop_gate_boundary_nine_accepted_eight_rejected(tmp_path):
    # ceil(10 * (1 - 0.10)) == 9: the smallest count still accepted is 9, and the
    # existing drop-gate tests (count=2 against previous_count=10) sit nowhere near
    # this boundary, so an off-by-one there would go uncaught.
    def fetcher_for(count, subdir):
        pages = {1: [product(i) for i in range(count)], 2: []}
        return PoliteFetcher(tmp_path / subdir, SV, delay=0.0,
                             transport=pages_transport(pages), clock=FakeClock())

    records, manifest = crawl_verified(
        fetcher_for(9, "nine"), "shop.test", attempt_id="a-9",
        previous_count=10, max_drop_fraction=0.10,
    )
    assert manifest["count"] == 9

    with pytest.raises(InconsistentCrawl, match="large catalog drop"):
        crawl_verified(
            fetcher_for(8, "eight"), "shop.test", attempt_id="a-8",
            previous_count=10, max_drop_fraction=0.10,
        )
