"""Query-side lexicon for BM25+Lex. Documents are indexed unchanged."""
from engine.tokenize import compound_tokens, split_compound, tokenize

# Gender/age prefixes that shoppers glue onto a head: herrjeans, damjacka.
MODIFIERS: frozenset[str] = frozenset({"herr", "dam", "barn"})

# English garment words seen in this catalog's titles, mapped to the Swedish
# singular head. Every value must be a head that compound splitting already
# emits on the document side (HEADS or a PLURALS value).
ENGLISH_HEADS: dict[str, str] = {
    "jacket": "jacka", "jackets": "jacka",
    "dress": "klänning", "dresses": "klänning",
    "shirt": "skjorta", "shirts": "skjorta",
    "bag": "väska", "bags": "väska",
    "coat": "kappa", "coats": "kappa",
    "sweater": "tröja", "sweaters": "tröja",
    "cap": "keps", "caps": "keps",
    "beanie": "mössa", "beanies": "mössa",
    "skirt": "kjol", "skirts": "kjol",
    "vest": "väst", "vests": "väst",
    "pants": "byxa", "trousers": "byxa",
    "blouse": "blus", "blouses": "blus",
    "boots": "känga",
}

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

    @classmethod
    def from_docs(cls, docs: list[tuple[str, dict[str, str]]]) -> "Lexicon":
        tokens: set[str] = set()
        for _doc_id, fields in docs:
            tokens.update(tokenize(fields.get("vendor", "")))
        return cls(tokens)

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

    def expand(self, tokens: list[str]) -> list[str]:
        out: list[str] = []

        def add(term: str) -> None:
            if term not in out:
                out.append(term)

        for token in tokens:
            for term in compound_tokens(token):
                add(term)
            split = split_compound(token)
            if split and split[0] in MODIFIERS:
                add(split[0])
            head = ENGLISH_HEADS.get(token)
            if head:
                add(head)
            fixed = self.correct_vendor(token)
            if fixed:
                add(fixed)
        return out

    def spec(self) -> dict:
        return {
            "modifiers": sorted(MODIFIERS),
            "english_heads": dict(ENGLISH_HEADS),
            "vendor_fuzzy": {
                "vocabulary": "tokens of the vendor field in the snapshot",
                "vendor_tokens": len(self.vendor_tokens),
                "max_edits": "0 below 5 chars, 1 below 8, else 2",
                "applies_when": "token is not an exact vendor token and exactly one vendor token is nearest",
            },
        }
