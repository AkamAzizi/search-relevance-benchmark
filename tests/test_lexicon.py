from engine.lexicon import ENGLISH_HEADS, MODIFIERS, Lexicon, edit_distance, max_edits
from engine.tokenize import HEADS, PLURALS

VENDOR_TOKENS = {
    "carhartt", "wip", "les", "deux", "filippa", "k", "acqua", "limone",
    "simone", "perele", "wood", "wool", "noir", "norr", "nude", "nudie",
    "j", "lindeberg", "levi", "s", "hoff", "hoka", "vans", "gant",
}


def test_edit_distance_is_levenshtein():
    assert edit_distance("carhart", "carhartt") == 1
    assert edit_distance("filipa", "filippa") == 1
    assert edit_distance("lindberg", "lindeberg") == 1
    assert edit_distance("abc", "abc") == 0
    assert edit_distance("", "abc") == 3
    assert edit_distance("kitten", "sitting") == 3


def test_max_edits_grows_with_token_length():
    assert max_edits("lego") == 0
    assert max_edits("levis") == 1
    assert max_edits("carhart") == 1
    assert max_edits("lindberg") == 2
    assert max_edits("skidpjäxor") == 2


def test_correct_vendor_fixes_one_edit_typos():
    lex = Lexicon(VENDOR_TOKENS)
    assert lex.correct_vendor("carhart") == "carhartt"
    assert lex.correct_vendor("filipa") == "filippa"
    assert lex.correct_vendor("levis") == "levi"
    assert lex.correct_vendor("lindberg") == "lindeberg"


def test_correct_vendor_leaves_exact_short_ambiguous_and_distant_tokens_alone():
    lex = Lexicon(VENDOR_TOKENS)
    assert lex.correct_vendor("carhartt") is None
    assert lex.correct_vendor("wool") is None
    assert lex.correct_vendor("lego") is None
    assert lex.correct_vendor("timone") is None
    assert lex.correct_vendor("iphone") is None
    assert lex.correct_vendor("skidpjäxor") is None


def test_english_heads_all_map_to_known_swedish_heads():
    singulars = set(HEADS) | set(PLURALS.values())
    assert ENGLISH_HEADS
    for english, swedish in ENGLISH_HEADS.items():
        assert english == english.lower()
        assert swedish in singulars, (english, swedish)


def test_expand_adds_modifier_prefix_and_keeps_compound_tokens():
    lex = Lexicon(VENDOR_TOKENS)
    assert lex.expand(["herrjeans"]) == ["herrjeans", "jeans", "herr"]
    assert lex.expand(["damjacka"]) == ["damjacka", "jacka", "dam"]
    assert "bomber" not in lex.expand(["bomberjacka"])
    assert "herr" in MODIFIERS


def test_expand_adds_english_head_and_vendor_correction():
    lex = Lexicon(VENDOR_TOKENS)
    assert lex.expand(["jacket"]) == ["jacket", "jacka"]
    assert lex.expand(["dress"]) == ["dress", "klänning"]
    assert lex.expand(["carhart"]) == ["carhart", "carhartt"]
    assert lex.expand(["filipa", "k"]) == ["filipa", "filippa", "k"]


def test_expand_leaves_absent_vocabulary_untouched():
    lex = Lexicon(VENDOR_TOKENS)
    assert lex.expand(["iphone"]) == ["iphone"]
    assert lex.expand(["lego"]) == ["lego"]
    assert lex.expand(["skidpjäxor"]) == ["skidpjäxor"]


def test_from_docs_reads_vendor_tokens_from_the_vendor_field():
    lex = Lexicon.from_docs([
        ("1", {"title": "Detroit Jacket", "vendor": "Carhartt WIP", "product_type": "Jackor", "tags": "", "body": ""}),
        ("2", {"title": "Hoodie", "vendor": "Les Deux", "product_type": "Tröjor", "tags": "", "body": ""}),
    ])
    assert lex.correct_vendor("carhart") == "carhartt"
    assert lex.spec()["vendor_fuzzy"]["vendor_tokens"] == 4
