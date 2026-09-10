"""Build local runs, capture native search, score, and render the public page."""
import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from catalog.fetch import PoliteFetcher, RequestProfile
from engine.bm25 import B, K1, WEIGHTS, Bm25Index
from engine.docs import fields_from_record, load_snapshot
from engine.lexicon import Lexicon
from eval.grade import qrels_for_query
from eval.native import capture_native
from eval.page import render_scorecard
from eval.score import score_systems

EXAMPLE_QUERY_IDS = ("q01", "q09", "q17", "q19", "q24")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _index(catalog: list[dict], compound: bool) -> Bm25Index:
    docs = [(str(rec["product_id"]), fields_from_record(rec)) for rec in catalog]
    return Bm25Index(docs, compound=compound)


def _index_lex(catalog: list[dict]) -> Bm25Index:
    docs = [(str(rec["product_id"]), fields_from_record(rec)) for rec in catalog]
    return Bm25Index(docs, compound=True, lexicon=Lexicon.from_docs(docs), coord=True)


def _holdout(path: Path) -> dict:
    other = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "queries": other["queries"],
        "systems": {
            name: {
                "label": system["label"],
                "answerable_ndcg": system["answerable_ndcg"],
                "absent_returned": system["absent_returned"],
            }
            for name, system in other["systems"].items()
        },
    }


def _run_local(index: Bm25Index, queries: list[dict], k: int) -> dict[str, list[str]]:
    return {
        query["id"]: [doc_id for doc_id, _score in index.search(query["query"], k=k)]
        for query in queries
    }


def _example(query: dict, native_ids: list[str], mine_ids: list[str],
             catalog: list[dict]) -> dict:
    titles = {str(rec["product_id"]): rec.get("title") or "" for rec in catalog}
    qrels = qrels_for_query(query, catalog)

    def rows(ids: list[str]) -> list[dict]:
        return [
            {"product_id": pid, "title": titles.get(pid, pid), "grade": qrels.get(pid, 0)}
            for pid in ids[:10]
        ]

    return {
        "id": query["id"],
        "query": query["query"],
        "native": rows(native_ids),
        "mine": rows(mine_ids),
    }


def run(snapshot_path: Path, manifest_path: Path, queries_path: Path, out_dir: Path,
        data_dir: Path, capture: bool, site_path: Path | None,
        host: str | None = None, holdout_path: Path | None = None) -> dict:
    snapshot_path = Path(snapshot_path)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    snapshot_hash = _sha256(snapshot_path)
    if snapshot_hash != manifest["snapshot_sha256"]:
        raise ValueError(
            f"snapshot sha256 {snapshot_hash} != manifest {manifest['snapshot_sha256']}"
        )
    catalog = load_snapshot(snapshot_path)
    queries_raw = json.loads(Path(queries_path).read_text(encoding="utf-8"))
    queries = queries_raw["queries"]
    k_run = int(queries_raw.get("k_run", 20))
    k_eval = int(queries_raw.get("k_eval", 10))
    short_label = queries_raw.get("short_label") or "Store A"
    display_name = queries_raw.get("display_name") or short_label
    store_id = queries_raw.get("store") or "store-a"
    crawl_host = host or queries_raw.get("host")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bm25_ids = _run_local(_index(catalog, compound=False), queries, k_run)
    compound_ids = _run_local(_index(catalog, compound=True), queries, k_run)
    lex_index = _index_lex(catalog)
    lex_ids = _run_local(lex_index, queries, k_run)

    run_spec = {
        "k1": K1,
        "b": B,
        "field_weights": WEIGHTS,
        "k_run": k_run,
        "k_eval": k_eval,
        "code": "engine.bm25.Bm25Index",
    }
    _write_json(out_dir / "runspec-bm25.json", {**run_spec, "system": "bm25", "compound": False})
    _write_json(out_dir / "runspec-bm25-compound.json", {
        **run_spec, "system": "bm25-compound", "compound": True,
    })
    _write_json(out_dir / "run-bm25.json", {"system": "bm25", "queries": bm25_ids})
    _write_json(out_dir / "run-bm25-compound.json", {
        "system": "bm25-compound", "queries": compound_ids,
    })
    _write_json(out_dir / "runspec-bm25-lex.json", {
        **run_spec, "system": "bm25-lex", "compound": True, "coord": True,
        "lexicon": lex_index.lexicon.spec() if lex_index.lexicon else {},
    })
    _write_json(out_dir / "run-bm25-lex.json", {"system": "bm25-lex", "queries": lex_ids})

    native_ids = {query["id"]: [] for query in queries}
    overlap = {"mapped": 0, "unmapped": 0}
    if capture:
        if not crawl_host:
            raise ValueError("native capture requires --host (live storefront host is not committed)")
        profile = RequestProfile(
            manifest["request_profile"]["locale"],
            manifest["request_profile"]["accept_language"],
        )
        fetcher = PoliteFetcher(Path(data_dir) / "cache", profile, delay=5.0)
        captured = capture_native(
            fetcher, crawl_host, queries, catalog,
            namespace=f"native-{manifest['run_id']}", k=k_run,
        )
        captured["domain"] = store_id
        _write_json(out_dir / "run-native.json", captured)
        native_ids = {
            qid: body["product_ids"] for qid, body in captured["queries"].items()
        }
        overlap = {"mapped": captured["mapped"], "unmapped": captured["unmapped"]}

    runs = {
        "native": native_ids,
        "bm25": bm25_ids,
        "bm25-compound": compound_ids,
        "bm25-lex": lex_ids,
    }
    scored = score_systems(runs, queries, catalog, k=k_eval)
    by_id = {query["id"]: query for query in queries}
    examples = [
        _example(by_id[qid], native_ids.get(qid, []), lex_ids.get(qid, []), catalog)
        for qid in EXAMPLE_QUERY_IDS
        if qid in by_id
    ]
    card = {
        "generated_at": datetime.now(UTC).isoformat(),
        "store": short_label,
        "display_name": display_name,
        "k": k_eval,
        "snapshot": {
            "run_id": manifest["run_id"],
            "count": manifest["count"],
            "sha256": snapshot_hash,
            "digest": manifest["digest"],
        },
        "queries": {
            "id": queries_raw["id"],
            "n": len(queries),
            "sha256": _sha256(Path(queries_path)),
            "committed_at": queries_raw.get("committed_at"),
        },
        "overlap": overlap,
        "systems": {
            "native": {**scored["systems"]["native"], "label": f"{short_label} native"},
            "bm25": {**scored["systems"]["bm25"], "label": "BM25"},
            "bm25-compound": {
                **scored["systems"]["bm25-compound"], "label": "BM25+Compound",
            },
            "bm25-lex": {**scored["systems"]["bm25-lex"], "label": "BM25+Lex"},
        },
        "per_query": scored["queries"],
        "examples": examples,
    }
    if holdout_path is not None:
        card["holdout"] = _holdout(Path(holdout_path))
    _write_json(out_dir / "scorecard.json", card)
    html = render_scorecard(card)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    if site_path is not None:
        site_path = Path(site_path)
        site_path.parent.mkdir(parents=True, exist_ok=True)
        site_path.write_text(html, encoding="utf-8")
    return card


def main() -> None:
    parser = argparse.ArgumentParser(description="Score native search against BM25.")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--queries", default="artifacts/queries/store-a-v1.json")
    parser.add_argument("--out", default="artifacts/store-a/scorecard-v1")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--site", default="site/index.html")
    parser.add_argument("--host", default=None,
                        help="live storefront host for native capture; not written to public artifacts")
    parser.add_argument("--holdout", default="",
                        help="scorecard.json of a held-out run to embed on the page")
    parser.add_argument("--capture-native", action="store_true")
    args = parser.parse_args()
    card = run(
        Path(args.snapshot), Path(args.manifest), Path(args.queries),
        Path(args.out), Path(args.data_dir), capture=args.capture_native,
        site_path=Path(args.site) if args.site else None,
        host=args.host,
        holdout_path=Path(args.holdout) if args.holdout else None,
    )
    print(f"store={card['store']} snapshot={card['snapshot']['run_id']} "
          f"products={card['snapshot']['count']}")
    for name, system in card["systems"].items():
        print(f"  {name}: nDCG@10={system['answerable_ndcg']:.3f} "
              f"P@10={system['precision']:.3f} "
              f"absent_returned={system['absent_returned']}")


if __name__ == "__main__":
    main()
