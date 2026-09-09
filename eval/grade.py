"""Catalog-grounded graded relevance. Rules are committed with the query set."""


def grade_product(product: dict, spec: dict) -> int:
    method = spec["method"]
    if method == "none":
        return 0
    if method == "vendor_equals":
        vendor = (product.get("vendor") or "").casefold()
        return int(spec["grade"]) if vendor == spec["vendor"].casefold() else 0
    if method == "product_type":
        product_type = product.get("product_type") or ""
        return int(spec.get("grades", {}).get(product_type, 0))
    if method == "tag_equals":
        want = spec["tag"].casefold()
        tags = [tag.casefold() for tag in (product.get("tags") or [])]
        return int(spec["grade"]) if want in tags else 0
    if method == "title_any":
        title = (product.get("title") or "").casefold()
        for token in spec["tokens"]:
            if token.casefold() in title:
                return int(spec["grade"])
        return 0
    if method == "all_of":
        total = 0
        for part in spec["parts"]:
            grade = grade_product(product, part)
            if part.get("required") and grade == 0:
                return 0
            total += grade
        return min(total, int(spec.get("max", total)))
    raise ValueError(f"unknown relevance method {method!r}")


def qrels_for_query(query: dict, catalog: list[dict]) -> dict[str, int]:
    spec = query["relevance"]
    qrels: dict[str, int] = {}
    for product in catalog:
        grade = grade_product(product, spec)
        if grade:
            qrels[str(product["product_id"])] = grade
    return qrels
