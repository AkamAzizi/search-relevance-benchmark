"""Project a catalog record into the weighted BM25 fields."""
import json
import re
from html import unescape
from pathlib import Path

def strip_html(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", html or ""))


def fields_from_record(rec: dict) -> dict[str, str]:
    tags = rec.get("tags") or []
    tag_text = " ".join(tags) if isinstance(tags, list) else str(tags)
    return {
        "title": rec.get("title") or "",
        "vendor": rec.get("vendor") or "",
        "product_type": rec.get("product_type") or "",
        "tags": tag_text,
        "body": strip_html(rec.get("body_html") or ""),
    }


def load_snapshot(path: Path) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]
