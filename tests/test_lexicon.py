from engine.lexicon import Lexicon, edit_distance, max_edits

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
