"""Walk Shopify's public products.json and prove the crawl was self-consistent."""
import hashlib
import json
import math
from collections import Counter

from catalog.record import normalize, source_payload_hash

PAGE_SIZE = 250


class InconsistentCrawl(Exception):
    """The crawl cannot prove it saw a consistent catalog. Discard it."""


def _decode_products(body: bytes) -> list[dict]:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InconsistentCrawl(f"response is not valid JSON: {exc}") from exc
    products = payload.get("products") if isinstance(payload, dict) else None
    if not isinstance(products, list):
        raise InconsistentCrawl("response does not contain a products list")
    for product in products:
        if not isinstance(product, dict) or "id" not in product:
            raise InconsistentCrawl("product element is not a dict with an id field")
    return products


def crawl_once(fetcher, domain: str, namespace: str, max_pages: int = 60) -> list[dict]:
    records: list[dict] = []
    for page in range(1, max_pages + 1):
        url = f"https://{domain}/products.json?limit={PAGE_SIZE}&page={page}"
        body = fetcher.get(url, namespace=namespace, validator=_decode_products)
        batch = _decode_products(body)
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
    entries = sorted(
        f"{record['product_id']}\x00{source_payload_hash(record)}" for record in records
    )
    joined = "\n".join(entries)
    return {
        "schema_version": 1,
        "count": len(ids),
        "digest": hashlib.sha256(joined.encode()).hexdigest(),
    }


def crawl_verified(fetcher, domain: str, attempt_id: str, max_pages: int = 60,
                   minimum_count: int = 1, previous_count: int | None = None,
                   max_drop_fraction: float = 0.10,
                   allow_large_drop: bool = False) -> tuple[list[dict], dict]:
    """Crawl twice and require both manifests to agree.

    Page-based pagination is unstable under concurrent catalog edits and the public
    endpoint offers no `since_id`, so consistency is detected rather than prevented.
    A crawl that cannot prove consistency must not become a benchmark.
    """
    first = crawl_once(
        fetcher, domain, namespace=f"{attempt_id}-a", max_pages=max_pages
    )
    first_manifest = build_manifest(first)

    second = crawl_once(
        fetcher, domain, namespace=f"{attempt_id}-b", max_pages=max_pages
    )
    second_manifest = build_manifest(second)

    if first_manifest["digest"] != second_manifest["digest"]:
        raise InconsistentCrawl(
            f"{domain}: catalog changed between crawls "
            f"({first_manifest['count']} then {second_manifest['count']} products). "
            f"Discard and re-crawl."
        )
    count = second_manifest["count"]
    if count < minimum_count:
        raise InconsistentCrawl(
            f"{domain}: count={count} is below minimum_count={minimum_count}; "
            "discard before sync"
        )
    if previous_count is not None and previous_count > 0 and not allow_large_drop:
        minimum_from_previous = math.ceil(previous_count * (1 - max_drop_fraction))
        if count < minimum_from_previous:
            raise InconsistentCrawl(
                f"{domain}: large catalog drop from {previous_count} to {count}; "
                f"maximum accepted fraction is {max_drop_fraction:.0%}. "
                "Investigate or pass the explicit large-drop override."
            )
    return second, second_manifest
