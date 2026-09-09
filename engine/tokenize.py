"""Tokenise catalog text. Compound splitting is opt-in and fashion-head specific."""
import re
from html import unescape

TOKEN_RE = re.compile(r"[0-9a-zåäöéèüæø]+", re.IGNORECASE)

# Longest first so "klänningar" wins over "klänning".
HEADS = (
    "klänningar", "pikétröjor", "piketrojor", "skjortor", "jackor", "väskor",
    "tröjor", "kepsar", "mössor", "blusar", "kjolar", "kappor", "västar",
    "kängor", "sneakers", "klänning", "pikétröja", "piketroja", "skjorta",
    "jacka", "väska", "tröja", "byxor", "byxa", "keps", "mössa", "blus",
    "kjol", "kappa", "väst", "jeans",
)

PLURALS = {
    "jackor": "jacka",
    "skjortor": "skjorta",
    "väskor": "väska",
    "klänningar": "klänning",
    "tröjor": "tröja",
    "pikétröjor": "pikétröja",
    "kepsar": "keps",
    "mössor": "mössa",
    "blusar": "blus",
    "kjolar": "kjol",
    "kappor": "kappa",
    "västar": "väst",
    "byxor": "byxa",
    "kängor": "känga",
}

MIN_PREFIX = 3


def tokenize(text: str) -> list[str]:
    stripped = unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return [match.group(0).lower() for match in TOKEN_RE.finditer(stripped)]


def split_compound(token: str) -> tuple[str, str] | None:
    """Return (prefix, head) when token is a compound ending in a known head."""
    token = token.lower()
    for head in HEADS:
        if token == head or not token.endswith(head):
            continue
        prefix = token[:-len(head)]
        if len(prefix) < MIN_PREFIX:
            continue
        return prefix, head
    return None


def compound_tokens(token: str) -> list[str]:
    token = token.lower()
    out = [token]
    if token in PLURALS and PLURALS[token] not in out:
        out.append(PLURALS[token])
    split = split_compound(token)
    if split:
        head = split[1]
        if head not in out:
            out.append(head)
        singular = PLURALS.get(head)
        if singular and singular not in out:
            out.append(singular)
    return out


def field_tokens(text: str, compound: bool) -> list[str]:
    tokens = tokenize(text)
    if not compound:
        return tokens
    out: list[str] = []
    for token in tokens:
        out.extend(compound_tokens(token))
    return out
