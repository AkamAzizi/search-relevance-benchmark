import json
import pytest
from catalog.fetch import PoliteFetcher, RequestProfile
from catalog.shopify import crawl_once, build_manifest, InconsistentCrawl

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
