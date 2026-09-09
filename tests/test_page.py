from eval.page import render_scorecard


def _card(**extra):
    card = {
        "store": "Store A",
        "display_name": "Swedish fashion retailer A",
        "k": 10,
        "snapshot": {"run_id": "anchor-003", "count": 1904, "sha256": "abc"},
        "queries": {"id": "store-a-v1", "sha256": "def", "n": 24},
        "overlap": {"mapped": 40, "unmapped": 2},
        "systems": {
            "native": {
                "label": "Store A native",
                "ndcg": 0.41,
                "answerable_ndcg": 0.48,
                "precision": 0.33,
                "absent_returned": 12,
                "by_stratum": {"compound": 0.2, "exact/brand": 0.9, "misspelling": 1.0},
            },
            "bm25-compound": {
                "label": "BM25+Compound",
                "ndcg": 0.55,
                "answerable_ndcg": 0.62,
                "precision": 0.40,
                "absent_returned": 8,
                "by_stratum": {"compound": 0.7, "exact/brand": 0.9, "misspelling": 0.4},
            },
            "bm25-lex": {
                "label": "BM25+Lex",
                "ndcg": 0.66,
                "answerable_ndcg": 0.71,
                "precision": 0.45,
                "absent_returned": 0,
                "by_stratum": {"compound": 0.7, "exact/brand": 0.9, "misspelling": 1.0},
            },
        },
        "examples": [
            {
                "query": "jacka",
                "native": [{"title": "Kevin Poly Jacket", "grade": 3}],
                "mine": [{"title": "Detroit Jacket - Black", "grade": 3}],
            }
        ],
    }
    card.update(extra)
    return card


def test_page_states_the_comparison_and_the_method():
    html = render_scorecard(_card())
    assert "Store A" in html
    assert "Swedish fashion retailer A" in html
    assert "zoovillage" not in html.lower()
    assert "0.710" in html
    assert "0.620" in html
    assert "Store A native vs BM25+Lex" in html
    assert "nDCG@10" in html
    assert "catalog-grounded" in html
    assert "Where they differ" in html
    assert "Kevin Poly Jacket" in html
    assert "store-a-v1" in html
    assert "after the v1 results" in html
    assert "Held-out check" not in html
    assert "<img" not in html


def test_page_falls_back_to_compound_when_lex_is_absent():
    card = _card()
    del card["systems"]["bm25-lex"]
    html = render_scorecard(card)
    assert "Store A native vs BM25+Compound" in html
    assert "0.620" in html


def test_page_renders_the_held_out_check_when_present():
    html = render_scorecard(_card(holdout={
        "queries": {"id": "store-a-v2", "n": 16, "sha256": "ghi"},
        "systems": {
            "native": {"label": "Store A native", "answerable_ndcg": 0.91, "absent_returned": 7},
            "bm25-lex": {"label": "BM25+Lex", "answerable_ndcg": 0.93, "absent_returned": 0},
        },
    }))
    assert "Held-out check" in html
    assert "store-a-v2" in html
    assert "0.930" in html
    assert "0.910" in html
