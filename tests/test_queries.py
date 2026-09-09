import json
from collections import Counter
from pathlib import Path


QUERIES = Path("artifacts/queries/store-a-v1.json")


def test_frozen_query_set_has_the_declared_shape():
    payload = json.loads(QUERIES.read_text())
    assert payload["id"] == "store-a-v1"
    assert payload["store"] == "store-a"
    assert payload["short_label"] == "Store A"
    assert "zoovillage" not in json.dumps(payload).lower()
    assert payload["committed_at"]
    ids = [q["id"] for q in payload["queries"]]
    assert len(ids) == 24
    assert len(set(ids)) == 24
    strata = Counter(q["stratum"] for q in payload["queries"])
    assert strata["exact/brand"] == 4
    assert strata["category"] == 4
    assert strata["compound"] == 3
    assert strata["attribute"] == 3
    assert strata["cross-language"] == 2
    assert strata["misspelling"] == 2
    assert strata["adversarial/absent"] == 3
    assert strata["natural language"] == 3
    for query in payload["queries"]:
        assert query["query"].strip()
        assert "method" in query["relevance"]


def test_committed_public_scorecard_does_not_name_the_retailer():
    html = Path("site/index.html").read_text()
    assert "zoovillage" not in html.lower()
    assert "Store A" in html
    assert "Swedish fashion retailer A" in html


HELD_OUT = Path("artifacts/queries/store-a-v2.json")


def test_held_out_query_set_has_the_declared_shape():
    payload = json.loads(HELD_OUT.read_text())
    assert payload["id"] == "store-a-v2"
    assert payload["store"] == "store-a"
    assert payload["short_label"] == "Store A"
    assert "zoovillage" not in json.dumps(payload).lower()
    assert "host" not in payload
    assert payload["committed_at"]
    ids = [q["id"] for q in payload["queries"]]
    assert len(ids) == 16
    assert len(set(ids)) == 16
    strata = Counter(q["stratum"] for q in payload["queries"])
    assert strata["exact/brand"] == 2
    assert strata["category"] == 2
    assert strata["compound"] == 2
    assert strata["attribute"] == 2
    assert strata["cross-language"] == 2
    assert strata["misspelling"] == 2
    assert strata["adversarial/absent"] == 2
    assert strata["natural language"] == 2
    v1 = {q["query"].casefold() for q in json.loads(QUERIES.read_text())["queries"]}
    for query in payload["queries"]:
        assert query["query"].strip()
        assert "method" in query["relevance"]
        assert query["query"].casefold() not in v1
