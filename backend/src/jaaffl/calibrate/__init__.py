"""Pre-draft calibration (Track J / E1–E3). Pure, importable measurement functions; the thin CLIs
under ``scripts/`` wire them to live data and write ``config/engine.json`` before the real draft."""

from jaaffl.calibrate.flex_split import flex_pool_counts, measure_flex_split
from jaaffl.calibrate.projections import (
    RegressionMetrics,
    compare_projection_sources,
    interval_coverage,
    regression_metrics,
)

__all__ = [
    "RegressionMetrics",
    "compare_projection_sources",
    "flex_pool_counts",
    "interval_coverage",
    "measure_flex_split",
    "regression_metrics",
]
