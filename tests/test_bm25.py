from engine.bm25 import Bm25Index
from engine.docs import fields_from_record


def _index(records, compound=False):
    docs = [(r["product_id"], fields_from_record(r)) for r in records]
    return Bm25Index(docs, compound=compound)


def test_vendor_query_ranks_that_brand_first():
    idx = _index([
        {"product_id": "1", "title": "Hoodie", "vendor": "Les Deux",
         "product_type": "Tröjor", "tags": [], "body_html": ""},
        {"product_id": "2", "title": "Jacket", "vendor": "Carhartt WIP",
         "product_type": "Jackor", "tags": [], "body_html": ""},
    ])
    ranked = [doc_id for doc_id, _ in idx.search("Les Deux", k=2)]
    assert ranked[0] == "1"


def test_plain_bm25_misses_swedish_compound_in_title():
    idx = _index([
        {"product_id": "1", "title": "Bomberjacka", "vendor": "X",
         "product_type": "Övrigt", "tags": [], "body_html": ""},
        {"product_id": "2", "title": "Les Deux Hoodie", "vendor": "Les Deux",
         "product_type": "Tröjor", "tags": [], "body_html": ""},
    ], compound=False)
    ranked = [doc_id for doc_id, _ in idx.search("jacka", k=2)]
    assert "1" not in ranked


def test_compound_bm25_retrieves_swedish_compound_in_title():
    idx = _index([
        {"product_id": "1", "title": "Bomberjacka", "vendor": "X",
         "product_type": "Övrigt", "tags": [], "body_html": ""},
        {"product_id": "2", "title": "Les Deux Hoodie", "vendor": "Les Deux",
         "product_type": "Tröjor", "tags": [], "body_html": ""},
    ], compound=True)
    ranked = [doc_id for doc_id, _ in idx.search("jacka", k=2)]
    assert ranked[0] == "1"


def test_compound_bm25_matches_plural_product_type_on_singular_query():
    idx = _index([
        {"product_id": "1", "title": "Detroit Jacket", "vendor": "Carhartt WIP",
         "product_type": "Jackor", "tags": [], "body_html": ""},
    ], compound=True)
    ranked = [doc_id for doc_id, _ in idx.search("jacka", k=1)]
    assert ranked == ["1"]


def test_search_returns_at_most_k_and_is_stable_for_empty_query():
    idx = _index([
        {"product_id": "1", "title": "A", "vendor": "V", "product_type": "T",
         "tags": [], "body_html": ""},
    ])
    assert idx.search("   ", k=10) == []
    assert len(idx.search("A", k=10)) == 1
