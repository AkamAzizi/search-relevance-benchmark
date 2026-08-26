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
    "created_at": "2026-07-01T10:00:00Z",
    "published_at": "2026-07-02T10:00:00Z",
    "updated_at": "2026-08-01T10:00:00Z",
    "options": [{"name": "Storlek", "position": 1, "values": ["M", "L"]}],
    "variants": [
        {"id": 91, "title": "M", "sku": "JACKET-M", "available": True,
         "price": "1299.00", "compare_at_price": None, "option1": "M"},
        {"id": 92, "title": "L", "sku": "JACKET-L", "available": False,
         "price": "1299.00", "compare_at_price": "1499.00", "option1": "L"},
    ],
    "images": [{"src": "https://cdn.shopify.com/x/bomber.jpg"}],
}


def test_normalize_extracts_expected_shape():
    rec = normalize(RAW)
    assert rec["product_id"] == "12345"
    assert rec["vendor"] == "Carhartt WIP"
    assert rec["tags"] == ["Herr", "Jackor", "ytterplagg"]      # sorted for hash stability
    assert rec["options"] == [{"name": "Storlek", "values": ["L", "M"]}]
    assert rec["variant_titles"] == ["M", "L"]
    assert rec["skus"] == ["JACKET-M", "JACKET-L"]
    assert rec["available"] == [True, False]
    assert rec["prices"] == ["1299.00", "1299.00"]
    assert rec["image_urls"] == ["https://cdn.shopify.com/x/bomber.jpg"]
    # The complete source response remains available for version history and audit.
    assert rec["source_payload"]["published_at"] == "2026-07-02T10:00:00Z"
    assert rec["source_payload"]["variants"][0]["id"] == 91


def test_tag_order_does_not_change_any_hash():
    shuffled = dict(RAW, tags=["Jackor", "ytterplagg", "Herr"])
    a, b = normalize(RAW), normalize(shuffled)
    assert source_payload_hash(a) == source_payload_hash(b)
    assert enrichment_input_hash(a) == enrichment_input_hash(b)


def test_price_change_moves_source_hash_but_not_enrichment_hash():
    variants = [dict(v, price="999.00") for v in RAW["variants"]]
    cheaper = dict(RAW, variants=variants)
    a, b = normalize(RAW), normalize(cheaper)
    assert source_payload_hash(a) != source_payload_hash(b)
    assert enrichment_input_hash(a) == enrichment_input_hash(b)


def test_availability_change_moves_source_hash_but_not_enrichment_hash():
    variants = [dict(RAW["variants"][0], available=False), RAW["variants"][1]]
    unavailable = dict(RAW, variants=variants)
    a, b = normalize(RAW), normalize(unavailable)
    assert source_payload_hash(a) != source_payload_hash(b)
    assert enrichment_input_hash(a) == enrichment_input_hash(b)


def test_option_value_change_moves_both_hashes():
    resized = dict(RAW, options=[{"name": "Storlek", "position": 1,
                                  "values": ["M", "L", "XL"]}])
    a, b = normalize(RAW), normalize(resized)
    assert source_payload_hash(a) != source_payload_hash(b)
    assert enrichment_input_hash(a) != enrichment_input_hash(b)


def test_title_change_moves_both_hashes():
    retitled = dict(RAW, title="Bomber Jacket - Navy")
    a, b = normalize(RAW), normalize(retitled)
    assert source_payload_hash(a) != source_payload_hash(b)
    assert enrichment_input_hash(a) != enrichment_input_hash(b)


def test_updated_at_alone_moves_neither_hash():
    # Some storefronts stamp updated_at with the response time, not an edit time.
    touched = dict(RAW, updated_at="2026-08-20T09:00:00Z")
    a, b = normalize(RAW), normalize(touched)
    assert source_payload_hash(a) == source_payload_hash(b)
    assert enrichment_input_hash(a) == enrichment_input_hash(b)


def test_variant_updated_at_alone_moves_neither_hash():
    variants = [dict(RAW["variants"][0], updated_at="2026-08-20T09:00:00Z"),
                RAW["variants"][1]]
    touched = dict(RAW, variants=variants)
    a, b = normalize(RAW), normalize(touched)
    assert source_payload_hash(a) == source_payload_hash(b)
    assert enrichment_input_hash(a) == enrichment_input_hash(b)


def test_updated_at_is_retained_in_source_payload_for_version_history():
    variants = [dict(RAW["variants"][0], updated_at="2026-07-15T00:00:00Z"),
                RAW["variants"][1]]
    with_variant_timestamp = dict(RAW, variants=variants)
    rec = normalize(with_variant_timestamp)
    # Not hashed (see test_updated_at_alone_moves_neither_hash), but still stored verbatim.
    assert rec["source_payload"]["updated_at"] == "2026-08-01T10:00:00Z"
    assert rec["source_payload"]["variants"][0]["updated_at"] == "2026-07-15T00:00:00Z"


def test_enrichment_fields_are_a_strict_subset():
    rec = normalize(RAW)
    assert set(ENRICHMENT_FIELDS) < set(rec)
