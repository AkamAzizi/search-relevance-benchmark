import pytest

from engine.bm25 import Bm25Index
from engine.docs import fields_from_record
from engine.lexicon import Lexicon


def _index(records, compound=False, lexicon=False, coord=False):
    docs = [(r["product_id"], fields_from_record(r)) for r in records]
    lex = Lexicon.from_docs(docs) if lexicon else None
    return Bm25Index(docs, compound=compound, lexicon=lex, coord=coord)


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


BRANDS = [
    {"product_id": "1", "title": "Detroit Jacket", "vendor": "Carhartt WIP",
     "product_type": "Jackor", "tags": [], "body_html": ""},
    {"product_id": "2", "title": "Hoodie", "vendor": "Les Deux",
     "product_type": "Tröjor", "tags": [], "body_html": ""},
]

JEANS = [
    {"product_id": "1", "title": "Slim Jeans", "vendor": "Nudie Jeans",
     "product_type": "Jeans", "tags": ["Dam"], "body_html": ""},
    {"product_id": "2", "title": "Loose Jeans", "vendor": "Nudie Jeans",
     "product_type": "Jeans", "tags": ["Herr"], "body_html": ""},
]


def test_lexicon_requires_compound_documents():
    docs = [(r["product_id"], fields_from_record(r)) for r in BRANDS]
    with pytest.raises(ValueError):
        Bm25Index(docs, compound=False, lexicon=Lexicon.from_docs(docs))


def test_compound_index_misses_a_vendor_typo():
    idx = _index(BRANDS, compound=True)
    assert idx.search("carhart", k=2) == []


def test_lexicon_index_corrects_a_vendor_typo():
    idx = _index(BRANDS, compound=True, lexicon=True)
    ranked = [doc_id for doc_id, _ in idx.search("carhart", k=2)]
    assert ranked == ["1"]


def test_lexicon_index_maps_english_head_to_swedish_product_type():
    idx = _index([
        {"product_id": "1", "title": "Bomberjacka", "vendor": "X",
         "product_type": "Jackor", "tags": [], "body_html": ""},
        {"product_id": "2", "title": "Hoodie", "vendor": "Y",
         "product_type": "Tröjor", "tags": [], "body_html": ""},
    ], compound=True, lexicon=True)
    ranked = [doc_id for doc_id, _ in idx.search("jacket", k=2)]
    assert ranked == ["1"]


def test_lexicon_index_still_returns_nothing_for_absent_vocabulary():
    idx = _index(BRANDS, compound=True, lexicon=True, coord=True)
    assert idx.search("iphone", k=5) == []
    assert idx.search("lego", k=5) == []


def test_coord_scales_each_score_by_the_share_of_query_terms_matched():
    # Query expands to [herrjeans, jeans, herr]. Doc 2 matches jeans and herr
    # (2 of 3 terms); doc 1 matches jeans only (1 of 3).
    without = dict(_index(JEANS, compound=True, lexicon=True, coord=False).search("herrjeans", k=2))
    with_coord = dict(_index(JEANS, compound=True, lexicon=True, coord=True).search("herrjeans", k=2))
    assert with_coord["2"] == pytest.approx(without["2"] * 2 / 3)
    assert with_coord["1"] == pytest.approx(without["1"] * 1 / 3)
    assert with_coord["2"] > with_coord["1"]
