"""E3 — projection-validation metrics (plan §12.3 item 3).

Pure, dependency-free (base $0 install) scoring of a projection against realized outcomes. MAE/RMSE
measure magnitude, Spearman measures ranking (what a draft board actually cares about), interval
coverage calibrates σ, and :func:`compare_projection_sources` enforces the design gate: the blend
must beat the best single source. The CLI recomputes realized points under the JAAFFL scoring map.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RegressionMetrics:
    n: int
    mae: float
    rmse: float
    spearman: float


def _aligned(
    predicted: Mapping[str, float], actual: Mapping[str, float]
) -> tuple[list[float], list[float]]:
    keys = [k for k in predicted if k in actual]
    if not keys:
        raise ValueError("no overlapping keys between predicted and actual")
    return [predicted[k] for k in keys], [actual[k] for k in keys]


def _average_ranks(values: list[float]) -> list[float]:
    """1-based ranks, ties assigned their group's average rank (the Spearman convention)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def _pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    mean_a, mean_b = sum(a) / n, sum(b) / n
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True))
    dev_a = sum((x - mean_a) ** 2 for x in a) ** 0.5
    dev_b = sum((y - mean_b) ** 2 for y in b) ** 0.5
    if dev_a == 0.0 or dev_b == 0.0:
        return 0.0
    return cov / (dev_a * dev_b)


def regression_metrics(
    predicted: Mapping[str, float], actual: Mapping[str, float]
) -> RegressionMetrics:
    """MAE, RMSE, and Spearman rank correlation over the keys ``predicted`` and ``actual`` share."""
    pred, act = _aligned(predicted, actual)
    n = len(pred)
    mae = sum(abs(p - a) for p, a in zip(pred, act, strict=True)) / n
    rmse = (sum((p - a) ** 2 for p, a in zip(pred, act, strict=True)) / n) ** 0.5
    spearman = _pearson(_average_ranks(pred), _average_ranks(act))
    return RegressionMetrics(n=n, mae=mae, rmse=rmse, spearman=spearman)


def interval_coverage(
    mu: Mapping[str, float],
    sigma: Mapping[str, float],
    actual: Mapping[str, float],
    *,
    z: float = 1.28,
) -> float:
    """Fraction of realized values falling inside ``[mu − z·σ, mu + z·σ]``. Default ``z=1.28`` is
    the ~80% band — a well-calibrated σ yields coverage ≈ 0.8."""
    keys = [k for k in mu if k in actual and k in sigma]
    if not keys:
        raise ValueError("no overlapping keys for coverage")
    inside = sum(1 for k in keys if mu[k] - z * sigma[k] <= actual[k] <= mu[k] + z * sigma[k])
    return inside / len(keys)


def compare_projection_sources(
    sources: Mapping[str, Mapping[str, float]],
    blend: Mapping[str, float],
    actual: Mapping[str, float],
) -> dict:
    """Score each single source and the blend against ``actual``; flag whether the blend's RMSE is
    at least as good as the best single source (the design gate — blend must beat best single)."""
    per_source = {name: regression_metrics(preds, actual) for name, preds in sources.items()}
    blend_metrics = regression_metrics(blend, actual)
    best_rmse = min((m.rmse for m in per_source.values()), default=float("inf"))
    return {
        "per_source": per_source,
        "blend": blend_metrics,
        "blend_beats_best": blend_metrics.rmse <= best_rmse,
    }
