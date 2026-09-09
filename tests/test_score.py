from eval.score import score_systems


CATALOG = [
    {"product_id": "1", "title": "Hoodie", "vendor": "Les Deux",
     "product_type": "Tröjor", "tags": ["Herr"]},
    {"product_id": "2", "title": "Jacket", "vendor": "Carhartt WIP",
     "product_type": "Jackor", "tags": ["Herr"]},
]

QUERIES = [
    {"id": "q1", "query": "Les Deux", "stratum": "exact/brand",
     "relevance": {"method": "vendor_equals", "vendor": "Les Deux", "grade": 3}},
    {"id": "q2", "query": "iphone", "stratum": "adversarial/absent",
     "relevance": {"method": "none"}},
]


def test_the_system_that_ranks_the_relevant_doc_first_wins_ndcg():
    card = score_systems(
        {
            "native": {"q1": ["2", "1"], "q2": ["1", "2"]},
            "mine": {"q1": ["1"], "q2": []},
        },
        QUERIES,
        CATALOG,
        k=10,
    )
    assert card["systems"]["mine"]["ndcg"] > card["systems"]["native"]["ndcg"]
    assert card["systems"]["mine"]["answerable_ndcg"] > card["systems"]["native"]["answerable_ndcg"]


def test_absent_queries_are_excluded_from_answerable_ndcg():
    card = score_systems(
        {"native": {"q1": ["1"], "q2": ["1"]}},
        QUERIES,
        CATALOG,
        k=10,
    )
    native = card["systems"]["native"]
    assert native["answerable_ndcg"] == 1.0
    assert native["absent_returned"] == 1
