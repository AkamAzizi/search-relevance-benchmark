"""Walk Shopify's public products.json and prove the crawl was self-consistent."""
import hashlib
import json
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
