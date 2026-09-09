"""Capture-and-replay for Shopify's shopper-facing /search page."""
import re
from urllib.parse import urlencode

from catalog.fetch import FetchError, PoliteFetcher

POS_RE = re.compile(
    r"/products/([^/?#\"']+)\?[^\"']*?_pos=(\d+)",
    re.IGNORECASE,
)


def search_url(domain: str, query: str) -> str:
    return f"https://{domain}/search?{urlencode({'q': query, 'type': 'product'})}"


def parse_search_html(html: str) -> list[str]:
    by_pos: dict[int, str] = {}
    for handle, pos in POS_RE.findall(html):
        rank = int(pos)
        if rank not in by_pos:
            by_pos[rank] = handle.lower()
    return [by_pos[rank] for rank in sorted(by_pos)]


def validate_search_html(body: bytes) -> None:
    lowered = body.lower()
    if b"<html" not in lowered and b"<!doctype html" not in lowered:
        raise FetchError("search response is not HTML")


def capture_native(fetcher: PoliteFetcher, domain: str, queries: list[dict],
                   snapshot: list[dict], namespace: str, k: int = 20,
                   retries: int = 4, retry_wait: float = 10.0) -> dict:
    handle_to_id = {rec["handle"].lower(): str(rec["product_id"]) for rec in snapshot}
    runs: dict[str, dict] = {}
    unmapped_total = 0
    mapped_total = 0
    for query in queries:
        url = search_url(domain, query["query"])
        body = _get_search(fetcher, url, namespace, retries, retry_wait)
        html = body.decode("utf-8", errors="replace")
        handles = parse_search_html(html)[:k]
        product_ids: list[str] = []
        missing: list[str] = []
        for handle in handles:
            product_id = handle_to_id.get(handle)
            if product_id:
                product_ids.append(product_id)
                mapped_total += 1
            else:
                missing.append(handle)
                unmapped_total += 1
        runs[query["id"]] = {
            "handles": handles,
            "product_ids": product_ids,
            "unmapped": missing,
        }
    return {
        "system": "native",
        "domain": domain,
        "k": k,
        "queries": runs,
        "mapped": mapped_total,
        "unmapped": unmapped_total,
    }


def _get_search(fetcher: PoliteFetcher, url: str, namespace: str,
                retries: int, retry_wait: float) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return fetcher.get(url, namespace=namespace, validator=validate_search_html)
        except FetchError as exc:
            last = exc
            if attempt + 1 == retries:
                break
            fetcher._clock.sleep(retry_wait * (attempt + 1))
    assert last is not None
    raise last
