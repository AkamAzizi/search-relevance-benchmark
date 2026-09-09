from catalog.fetch import FetchError, PoliteFetcher, RequestProfile
from eval.native import capture_native, parse_search_html, search_url


SV = RequestProfile("sv-SE", "sv-SE,sv;q=0.9,en;q=0.5")


class FakeClock:
    def __init__(self): self.t = 0.0
    def monotonic(self): return self.t
    def sleep(self, s): self.t += s


SAMPLE = """
<html><title>Sökning: 2 resultat</title>
<a href="/products/detroit-jacket-black?_pos=2&amp;_sid=abc&amp;_ss=r">b</a>
<a href="/products/detroit-jacket-black?_pos=2&amp;_sid=abc&amp;_ss=r">b again</a>
<a href="/products/les-deux-hoodie?_pos=1&amp;_sid=abc&amp;_ss=r">a</a>
<a href="/collections/all">ignore</a>
</html>
"""


def test_parse_search_html_orders_by_pos_and_dedupes():
    assert parse_search_html(SAMPLE) == ["les-deux-hoodie", "detroit-jacket-black"]


def test_parse_search_html_empty_when_no_products():
    assert parse_search_html("<html><title>Sökning: 0 resultat</title></html>") == []


def test_search_url_encodes_query_and_forces_product_type():
    url = search_url("shop.example", "Les Deux")
    assert url.startswith("https://shop.example/search?")
    assert "type=product" in url
    assert "Les+Deux" in url or "Les%20Deux" in url


def test_capture_native_maps_handles_and_records_overlap(tmp_path):
    html = (
        "<html><title>Search</title>"
        '<a href="/products/in-snapshot?_pos=1&amp;_ss=r">a</a>'
        '<a href="/products/not-in-snapshot?_pos=2&amp;_ss=r">b</a>'
        "</html>"
    ).encode("ascii")
    calls = []

    def transport(url, profile):
        calls.append(url)
        return html

    fetcher = PoliteFetcher(tmp_path, SV, delay=0.0, transport=transport, clock=FakeClock())
    snapshot = [{"handle": "in-snapshot", "product_id": "99"}]
    queries = [{"id": "q01", "query": "Les Deux"}]
    captured = capture_native(
        fetcher, "shop.example", queries, snapshot, namespace="run-1", k=20,
    )
    assert captured["queries"]["q01"]["product_ids"] == ["99"]
    assert captured["queries"]["q01"]["unmapped"] == ["not-in-snapshot"]
    assert captured["mapped"] == 1
    assert captured["unmapped"] == 1
    assert calls == [search_url("shop.example", "Les Deux")]


def test_capture_native_retries_transient_fetch_errors(tmp_path):
    html = (
        "<html><title>Search</title>"
        '<a href="/products/in-snapshot?_pos=1&amp;_ss=r">a</a>'
        "</html>"
    ).encode("ascii")
    calls = {"n": 0}

    def transport(url, profile):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FetchError("curl exit 22: 503")
        return html

    fetcher = PoliteFetcher(tmp_path, SV, delay=0.0, transport=transport, clock=FakeClock())
    captured = capture_native(
        fetcher, "shop.example",
        [{"id": "q01", "query": "lego"}],
        [{"handle": "in-snapshot", "product_id": "99"}],
        namespace="run-1", k=20, retries=3, retry_wait=0.0,
    )
    assert captured["queries"]["q01"]["product_ids"] == ["99"]
    assert calls["n"] == 2
