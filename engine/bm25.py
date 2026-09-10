"""Fielded Okapi BM25. Scores are a weighted sum of per-field BM25."""
import math
from collections import Counter, defaultdict

from engine.lexicon import Lexicon
from engine.tokenize import field_tokens, tokenize

WEIGHTS = {
    "title": 5.0,
    "vendor": 4.0,
    "product_type": 3.0,
    "tags": 2.0,
    "body": 1.0,
}

K1 = 1.2
B = 0.75


class Bm25Index:
    def __init__(self, docs: list[tuple[str, dict[str, str]]], compound: bool = False,
                 k1: float = K1, b: float = B, weights: dict[str, float] | None = None,
                 lexicon: Lexicon | None = None, coord: bool = False):
        if lexicon is not None and not compound:
            raise ValueError("lexicon requires compound=True so document heads match query heads")
        self.compound = compound
        self.lexicon = lexicon
        self.coord = coord
        self.k1 = k1
        self.b = b
        self.weights = dict(weights or WEIGHTS)
        self.doc_ids: list[str] = []
        self.tf: dict[str, list[Counter[str]]] = {field: [] for field in self.weights}
        self.dl: dict[str, list[int]] = {field: [] for field in self.weights}
        self.df: dict[str, dict[str, int]] = {field: defaultdict(int) for field in self.weights}
        self.avgdl: dict[str, float] = {}

        for doc_id, fields in docs:
            self.doc_ids.append(doc_id)
            for field in self.weights:
                tokens = field_tokens(fields.get(field, ""), compound)
                counts = Counter(tokens)
                self.tf[field].append(counts)
                self.dl[field].append(len(tokens))
                for term in counts:
                    self.df[field][term] += 1

        n = len(self.doc_ids)
        for field in self.weights:
            total = sum(self.dl[field])
            self.avgdl[field] = (total / n) if n else 0.0

    def _idf(self, field: str, term: str) -> float:
        n_qi = self.df[field].get(term, 0)
        n = len(self.doc_ids)
        return math.log(1.0 + (n - n_qi + 0.5) / (n_qi + 0.5))

    def _query_tokens(self, query: str) -> list[str]:
        if self.lexicon is not None:
            return self.lexicon.expand(tokenize(query))
        return field_tokens(query, self.compound)

    def search(self, query: str, k: int = 20) -> list[tuple[str, float]]:
        q_tokens = self._query_tokens(query)
        n = len(self.doc_ids)
        if not q_tokens or n == 0:
            return []
        scores = [0.0] * n
        matched: list[set[str]] = [set() for _ in range(n)]
        unique = set(q_tokens)
        for field, weight in self.weights.items():
            avgdl = self.avgdl[field] or 1.0
            for term in unique:
                idf = self._idf(field, term)
                for i, tfs in enumerate(self.tf[field]):
                    freq = tfs.get(term, 0)
                    if not freq:
                        continue
                    dl = self.dl[field][i]
                    denom = freq + self.k1 * (1 - self.b + self.b * dl / avgdl)
                    scores[i] += weight * idf * (freq * (self.k1 + 1)) / denom
                    matched[i].add(term)
        if self.coord:
            total = len(unique)
            scores = [score * len(matched[i]) / total for i, score in enumerate(scores)]
        ranked = sorted(
            ((self.doc_ids[i], scores[i]) for i in range(n) if scores[i] > 0),
            key=lambda item: (-item[1], item[0]),
        )
        return ranked[:k]
