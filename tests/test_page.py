from eval.page import render_scorecard


def test_page_states_the_comparison_and_the_method():
    html = render_scorecard(
        {
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
                    "by_stratum": {"compound": 0.2, "exact/brand": 0.9},
                },
                "bm25-compound": {
                    "label": "BM25+Compound",
                    "ndcg": 0.55,
                    "answerable_ndcg": 0.62,
                    "precision": 0.40,
                    "absent_returned": 8,
                    "by_stratum": {"compound": 0.7, "exact/brand": 0.9},
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
    )
    assert "Store A" in html
    assert "Swedish fashion retailer A" in html
    assert "zoovillage" not in html.lower()
    assert "0.620" in html or "0.62" in html
    assert "BM25+Compound" in html
    assert "nDCG@10" in html
    assert "catalog-grounded" in html
    assert "Where they differ" in html
    assert "Kevin Poly Jacket" in html
    assert "<img" not in html
