"""E3 — projection-validation metrics (plan §12.3 item 3, Track J).

Pure, dependency-free scoring of a projection against realized outcomes: MAE / RMSE / Spearman,
interval coverage for σ calibration, and a blend-vs-single-source comparison (the blend must beat
the best single source). The CLI recomputes realized points under the JAAFFL map and feeds these.
"""

from __future__ import annotations

import pytest

from jaaffl.calibrate.projections import (
    compare_projection_sources,
    interval_coverage,
    regression_metrics,
)


def test_perfect_prediction_scores_zero_error_and_unit_rank_correlation() -> None:
    values = {"a": 10.0, "b": 20.0, "c": 30.0}
    m = regression_metrics(values, dict(values))
    assert m.n == 3
    assert m.mae == pytest.approx(0.0)
    assert m.rmse == pytest.approx(0.0)
    assert m.spearman == pytest.approx(1.0)


def test_mae_and_rmse_match_hand_computation() -> None:
    predicted = {"a": 10.0, "b": 20.0, "c": 30.0}
    actual = {"a": 12.0, "b": 18.0, "c": 33.0}  # errors 2, 2, 3
    m = regression_metrics(predicted, actual)
    assert m.mae == pytest.approx(7 / 3)
    assert m.rmse == pytest.approx((17 / 3) ** 0.5)
    assert m.spearman == pytest.approx(1.0)  # both strictly increasing


def test_spearman_is_minus_one_for_a_reversed_ranking() -> None:
    predicted = {"a": 1.0, "b": 2.0, "c": 3.0}
    actual = {"a": 3.0, "b": 2.0, "c": 1.0}
    assert regression_metrics(predicted, actual).spearman == pytest.approx(-1.0)


def test_metrics_align_on_common_keys_only() -> None:
    predicted = {"a": 10.0, "b": 20.0, "missing_in_actual": 5.0}
    actual = {"a": 10.0, "b": 20.0, "only_in_actual": 9.0}
    assert regression_metrics(predicted, actual).n == 2


def test_interval_coverage_counts_actuals_inside_the_band() -> None:
    mu = {"a": 10.0, "b": 10.0}
    sigma = {"a": 5.0, "b": 5.0}
    actual = {"a": 11.0, "b": 20.0}  # z=1.28 → band [3.6, 16.4]; a inside, b outside
    assert interval_coverage(mu, sigma, actual, z=1.28) == pytest.approx(0.5)


def test_blend_comparison_flags_when_the_blend_beats_the_best_single_source() -> None:
    actual = {"a": 10.0, "b": 20.0, "c": 30.0}
    sources = {
        "s1": {"a": 8.0, "b": 20.0, "c": 33.0},  # some error
        "s2": {"a": 12.0, "b": 20.0, "c": 27.0},  # some error
    }
    blend = {"a": 10.0, "b": 20.0, "c": 30.0}  # exact → best possible
    report = compare_projection_sources(sources, blend, actual)
    assert set(report["per_source"]) == {"s1", "s2"}
    assert report["blend"].rmse == pytest.approx(0.0)
    assert report["blend_beats_best"] is True


def test_empty_overlap_raises_rather_than_dividing_by_zero() -> None:
    with pytest.raises(ValueError):
        regression_metrics({"a": 1.0}, {"b": 2.0})
