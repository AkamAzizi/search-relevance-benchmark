from engine.lexicon import edit_distance, max_edits


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
