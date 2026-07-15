"""Draft optimization engine (Stage 5).

A transparent four-stage pipeline — projections -> league translation -> opponent model ->
simulation/optimization — orchestrated by :func:`recommend`. Residual ML (XGBoost),
injury-risk calibration, and 2027 aging curves layer on *after* this is stable.
"""

from jaaffl.engine.recommend import recommend

__all__ = ["recommend"]
