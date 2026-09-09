from eval.grade import grade_product, qrels_for_query


CATALOG = [
    {"product_id": "1", "title": "Track Pants - Black", "vendor": "Les Deux",
     "product_type": "Byxor", "tags": ["Herr"]},
    {"product_id": "2", "title": "Detroit Jacket - Black", "vendor": "Carhartt WIP",
     "product_type": "Jackor", "tags": ["Herr", "skinn"]},
    {"product_id": "3", "title": "Leo Dress - Brown", "vendor": "YAS",
     "product_type": "Klänningar", "tags": ["Dam"]},
    {"product_id": "4", "title": "Red Dress - Rouge", "vendor": "YAS",
     "product_type": "Klänningar", "tags": ["Dam"]},
]


def test_vendor_equals_is_binary_graded():
    spec = {"method": "vendor_equals", "vendor": "Les Deux", "grade": 3}
    assert grade_product(CATALOG[0], spec) == 3
    assert grade_product(CATALOG[1], spec) == 0


def test_product_type_grades_are_looked_up():
    spec = {"method": "product_type", "grades": {"Jackor": 3, "Kappor": 2}}
    assert grade_product(CATALOG[1], spec) == 3
    assert grade_product(CATALOG[0], spec) == 0


def test_tag_equals_is_case_insensitive():
    spec = {"method": "tag_equals", "tag": "Ull", "grade": 3}
    assert grade_product({"product_id": "x", "title": "", "vendor": "",
                          "product_type": "", "tags": ["ull"]}, spec) == 3


def test_all_of_sums_and_clips():
    spec = {
        "method": "all_of",
        "max": 3,
        "parts": [
            {"method": "product_type", "grades": {"Jackor": 2}, "required": True},
            {"method": "tag_equals", "tag": "skinn", "grade": 1},
            {"method": "title_any", "tokens": ["black", "svart"], "grade": 1},
        ],
    }
    assert grade_product(CATALOG[1], spec) == 3
    assert grade_product(CATALOG[0], spec) == 0


def test_none_method_grades_everything_zero():
    assert grade_product(CATALOG[0], {"method": "none"}) == 0


def test_qrels_omit_zeros():
    query = {"id": "q01", "relevance": {"method": "vendor_equals",
                                       "vendor": "Les Deux", "grade": 3}}
    qrels = qrels_for_query(query, CATALOG)
    assert qrels == {"1": 3}
