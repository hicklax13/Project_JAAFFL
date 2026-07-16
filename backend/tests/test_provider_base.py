"""AdpRecord + the widened adp() contract (plan §4.1).

The survival math S_j(N)=1-Phi((N-m_j)/s_j) needs the stdev, not just the ADP mean, so the
provider protocol carries an AdpRecord (adp + stdev + range) rather than a bare float.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jaaffl.providers.base import AdpRecord, Capability, FantasyDataProvider


def test_adp_record_holds_the_survival_inputs() -> None:
    r = AdpRecord(adp=12.3, stdev=4.5, high=8, low=20, times_drafted=100, bye=9)
    assert r.adp == 12.3
    assert r.stdev == 4.5
    assert r.high == 8
    assert r.low == 20
    assert r.times_drafted == 100
    assert r.bye == 9


def test_adp_record_requires_adp_and_defaults_optionals_to_none() -> None:
    r = AdpRecord(adp=1.0)
    assert r.adp == 1.0
    assert r.stdev is None
    assert r.high is None
    assert r.low is None
    assert r.times_drafted is None
    assert r.bye is None


def test_adp_record_is_frozen() -> None:
    r = AdpRecord(adp=1.0)
    with pytest.raises(ValidationError):
        r.adp = 2.0  # type: ignore[misc]


def test_adp_record_rejects_missing_adp() -> None:
    with pytest.raises(ValidationError):
        AdpRecord()  # type: ignore[call-arg]


def test_adp_boundary_is_adprecord_typed() -> None:
    # The protocol widened dict[str, float] -> dict[str, AdpRecord]; the annotation pins it.
    assert FantasyDataProvider.adp.__annotations__["return"] == "dict[str, AdpRecord]"


def test_expected_points_capability_exists() -> None:
    assert Capability.EXPECTED_POINTS in set(Capability)
