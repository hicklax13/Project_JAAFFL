"""League translation layer (Stage 2): CBS scoring, replacement values, scarcity."""

from jaaffl.league.coverage import board_coverage_gaps, startable_positions
from jaaffl.league.replacement import (
    dynamic_replacement_values,
    replacement_values,
    starter_demand,
)
from jaaffl.league.scoring import league_points

__all__ = [
    "board_coverage_gaps",
    "dynamic_replacement_values",
    "league_points",
    "replacement_values",
    "startable_positions",
    "starter_demand",
]
