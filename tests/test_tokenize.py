from engine.tokenize import compound_tokens, split_compound, tokenize


def test_tokenize_lowercases_and_keeps_swedish_letters():
    assert tokenize("Röd Klänning, ÅÄÖ!") == ["röd", "klänning", "åäö"]


def test_tokenize_splits_on_html_and_punctuation():
    assert tokenize("<p>Bomber Jacket — Black</p>") == ["bomber", "jacket", "black"]


def test_compound_tokens_emit_head_and_keep_original():
    assert compound_tokens("bomberjacka") == ["bomberjacka", "jacka"]


def test_compound_tokens_depluralize_known_heads():
    assert "jacka" in compound_tokens("jackor")
    assert "skjorta" in compound_tokens("skjortor")
    assert "väska" in compound_tokens("väskor")


def test_compound_tokens_leave_short_or_unknown_words_alone():
    assert compound_tokens("les") == ["les"]
    assert compound_tokens("deux") == ["deux"]


def test_compound_tokens_do_not_split_the_head_itself():
    assert compound_tokens("jacka") == ["jacka"]


def test_split_compound_returns_prefix_and_head():
    assert split_compound("bomberjacka") == ("bomber", "jacka")
    assert split_compound("herrjeans") == ("herr", "jeans")
    assert split_compound("skinnjacka") == ("skinn", "jacka")


def test_split_compound_prefers_the_longest_head():
    assert split_compound("sommarklänningar") == ("sommar", "klänningar")


def test_split_compound_returns_none_for_heads_and_unknown_words():
    assert split_compound("jacka") is None
    assert split_compound("deux") is None
    assert split_compound("iphone") is None
