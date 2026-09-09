"""Query-side lexicon for BM25+Lex. Documents are indexed unchanged."""

EDITS_BY_LENGTH = ((5, 0), (8, 1))


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ca != cb),
            ))
        previous = current
    return previous[-1]


def max_edits(token: str) -> int:
    for below, edits in EDITS_BY_LENGTH:
        if len(token) < below:
            return edits
    return 2


class Lexicon:
    def __init__(self, vendor_tokens: set[str] | frozenset[str]):
        self.vendor_tokens: list[str] = sorted(vendor_tokens)
        self._vendor_set = set(self.vendor_tokens)

    def correct_vendor(self, token: str) -> str | None:
        if token in self._vendor_set:
            return None
        budget = max_edits(token)
        if budget == 0:
            return None
        best: list[str] = []
        best_distance = budget + 1
        for candidate in self.vendor_tokens:
            if abs(len(candidate) - len(token)) > budget:
                continue
            distance = edit_distance(token, candidate)
            if distance < best_distance:
                best_distance, best = distance, [candidate]
            elif distance == best_distance:
                best.append(candidate)
        if best_distance <= budget and len(best) == 1:
            return best[0]
        return None
