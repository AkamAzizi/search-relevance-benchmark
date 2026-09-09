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
