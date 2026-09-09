from eval.metrics import dcg_at, ndcg_at, precision_at


def test_perfect_ranking_is_one():
    assert ndcg_at([3, 2, 0], k=3) == 1.0


def test_empty_ideal_is_zero():
    assert ndcg_at([0, 0, 0], k=3) == 0.0
    assert ndcg_at([], k=10) == 0.0


def test_swapped_relevant_docs_score_below_perfect():
    swapped = ndcg_at([2, 3, 0], k=3)
    assert 0.0 < swapped < 1.0


def test_dcg_cutoff_does_not_see_rank_four():
    assert dcg_at([3, 0, 0, 3], k=3) == dcg_at([3, 0, 0], k=3)


def test_idcg_uses_the_full_relevant_set():
    missed = ndcg_at([3, 0, 0], k=3, ideal=[3, 3])
    assert 0.0 < missed < 1.0
    assert ndcg_at([3, 3, 0], k=3, ideal=[3, 3]) == 1.0


def test_precision_counts_grade_at_least_two():
    assert precision_at([3, 2, 1, 0], k=4, relevant_at=2) == 0.5
    assert precision_at([0, 0], k=10, relevant_at=2) == 0.0
