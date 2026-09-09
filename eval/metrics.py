"""Ranking metrics. nDCG uses gain 2^rel - 1."""
import math


def dcg_at(gains: list[int], k: int) -> float:
    total = 0.0
    for rank, rel in enumerate(gains[:k], start=1):
        total += (2 ** rel - 1) / math.log2(rank + 1)
    return total


def ndcg_at(gains: list[int], k: int, ideal: list[int] | None = None) -> float:
    actual = dcg_at(gains, k)
    ideal_gains = sorted(ideal if ideal is not None else gains, reverse=True)
    ceiling = dcg_at(ideal_gains, k)
    if ceiling == 0:
        return 0.0
    return actual / ceiling


def precision_at(gains: list[int], k: int, relevant_at: int = 2) -> float:
    if k <= 0:
        return 0.0
    hits = sum(1 for gain in gains[:k] if gain >= relevant_at)
    return hits / k
