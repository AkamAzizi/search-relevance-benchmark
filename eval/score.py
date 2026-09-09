"""Score frozen runs against catalog-grounded qrels."""
from statistics import mean

from eval.grade import qrels_for_query
from eval.metrics import ndcg_at, precision_at

ABSENT = "adversarial/absent"


def _gains(product_ids: list[str], qrels: dict[str, int], k: int) -> list[int]:
    return [qrels.get(pid, 0) for pid in product_ids[:k]]


def _mean(values: list[float]) -> float:
    return mean(values) if values else 0.0


def score_systems(runs: dict[str, dict[str, list[str]]], queries: list[dict],
                  catalog: list[dict], k: int = 10) -> dict:
    qrels_by_id = {query["id"]: qrels_for_query(query, catalog) for query in queries}
    systems = {}
    per_query: list[dict] = []

    for name, run in runs.items():
        ndcgs: list[float] = []
        answerable: list[float] = []
        precisions: list[float] = []
        absent_returned = 0
        strata: dict[str, list[float]] = {}
        for query in queries:
            qrels = qrels_by_id[query["id"]]
            ids = list(run.get(query["id"], []))
            gains = _gains(ids, qrels, k)
            ideal = list(qrels.values())
            ndcg = ndcg_at(gains, k, ideal=ideal)
            precision = precision_at(gains, k, relevant_at=2)
            ndcgs.append(ndcg)
            precisions.append(precision)
            strata.setdefault(query["stratum"], []).append(ndcg)
            if query["stratum"] == ABSENT:
                absent_returned += len(ids)
            else:
                answerable.append(ndcg)
            per_query.append({
                "system": name,
                "id": query["id"],
                "query": query["query"],
                "stratum": query["stratum"],
                "ndcg": ndcg,
                "precision": precision,
                "returned": len(ids),
                "relevant": sum(1 for grade in qrels.values() if grade >= 2),
            })
        systems[name] = {
            "ndcg": _mean(ndcgs),
            "precision": _mean(precisions),
            "answerable_ndcg": _mean(answerable),
            "absent_returned": absent_returned,
            "by_stratum": {stratum: _mean(vals) for stratum, vals in strata.items()},
        }

    return {"k": k, "systems": systems, "queries": per_query}
