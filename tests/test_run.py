import hashlib
import json

from catalog.record import normalize
from eval.run import run


def _record(pid, title, vendor, product_type, handle):
    return normalize({
        "id": pid, "handle": handle, "title": title, "body_html": "",
        "vendor": vendor, "product_type": product_type, "tags": ["Herr"],
        "options": [], "images": [],
        "variants": [{"id": pid * 10, "title": "M", "price": "10.00"}],
        "updated_at": "2026-01-01T00:00:00Z",
    })


def _fixture(tmp_path):
    records = [
        _record(1, "Les Deux Hoodie", "Les Deux", "Tröjor", "les-deux-hoodie"),
        _record(2, "Bomberjacka", "Carhartt WIP", "Jackor", "bomberjacka"),
    ]
    snapshot = tmp_path / "snapshot.jsonl"
    snapshot.write_text("".join(
        json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n"
        for rec in sorted(records, key=lambda r: r["product_id"])
    ), encoding="utf-8")
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "run_id": "t1", "count": 2, "digest": "x", "snapshot_sha256": digest,
        "request_profile": {"locale": "sv-SE", "accept_language": "sv-SE"},
        "domain": "shop.test",
    }), encoding="utf-8")
    queries = tmp_path / "queries.json"
    queries.write_text(json.dumps({
        "id": "t", "store": "store-t", "short_label": "Store T",
        "display_name": "Test retailer T", "k_run": 10, "k_eval": 10,
        "queries": [
            {"id": "q01", "query": "Les Deux", "stratum": "exact/brand",
             "relevance": {"method": "vendor_equals", "vendor": "Les Deux", "grade": 3}},
            {"id": "q02", "query": "carhart", "stratum": "misspelling",
             "relevance": {"method": "vendor_equals", "vendor": "Carhartt WIP", "grade": 3}},
        ],
    }), encoding="utf-8")
    return snapshot, manifest, queries


def test_run_scores_local_systems_without_native_capture(tmp_path):
    snapshot, manifest, queries = _fixture(tmp_path)
    out = tmp_path / "out"
    card = run(snapshot, manifest, queries, out, tmp_path, capture=False,
               site_path=tmp_path / "site.html")
    assert card["systems"]["bm25-compound"]["answerable_ndcg"] == 0.5
    assert card["systems"]["bm25-lex"]["answerable_ndcg"] == 1.0
    assert card["systems"]["bm25-lex"]["label"] == "BM25+Lex"
    assert card["systems"]["native"]["label"] == "Store T native"
    assert (out / "scorecard.json").exists()
    assert (out / "run-bm25-lex.json").exists()
    spec = json.loads((out / "runspec-bm25-lex.json").read_text())
    assert spec["compound"] is True
    assert spec["coord"] is True
    assert "vendor_fuzzy" in spec["lexicon"]
    html = (tmp_path / "site.html").read_text()
    assert "nDCG@10" in html
    assert "BM25+Lex" in html
    assert "holdout" not in card
