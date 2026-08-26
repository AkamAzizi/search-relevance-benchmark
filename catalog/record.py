"""Retain Shopify source records and project their search-relevant fields (spec 6.1)."""
from copy import deepcopy
import hashlib
import json

# Search-relevant fields only. Drives enrichment caching, so price churn never re-pays
# for enrichment.
ENRICHMENT_FIELDS = (
    "title", "body_html", "tags", "vendor", "product_type", "options", "variant_titles",
)


def normalize(raw: dict) -> dict:
    # Retain every field the endpoint exposed. Only tag order is canonicalised because
    # Shopify tag order is not semantic and otherwise manufactures versions.
    source_payload = deepcopy(raw)
    source_payload["tags"] = sorted(source_payload.get("tags") or [])
    variants = raw.get("variants") or []
    return {
        "product_id": str(raw["id"]),
        "handle": raw.get("handle") or "",
        "title": raw.get("title") or "",
        "body_html": raw.get("body_html") or "",
        "vendor": raw.get("vendor") or "",
        "product_type": raw.get("product_type") or "",
        "tags": sorted(raw.get("tags") or []),
        "options": [
            {"name": o.get("name", ""),
             "values": sorted(str(v) for v in (o.get("values") or []))}
            for o in (raw.get("options") or [])
        ],
        "variant_ids": [str(v.get("id", "")) for v in variants],
        "variant_titles": [v.get("title", "") for v in variants],
        "variant_options": [
            [v.get(f"option{i}") for i in range(1, 4) if v.get(f"option{i}") is not None]
            for v in variants
        ],
        "skus": [v.get("sku") or "" for v in variants],
        "available": [bool(v.get("available")) for v in variants],
        "prices": [v.get("price") for v in variants],
        "compare_at_prices": [v.get("compare_at_price") for v in variants],
        # URLs only. Images are never downloaded or rehosted (invariant 7).
        "image_urls": [i.get("src", "") for i in (raw.get("images") or [])],
        "source_payload": source_payload,
    }


def _digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def source_payload_hash(rec: dict) -> str:
    return _digest(rec["source_payload"])


def enrichment_input_hash(rec: dict) -> str:
    return _digest({k: rec[k] for k in ENRICHMENT_FIELDS})
