from engine.tokenize import compound_tokens, tokenize


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
