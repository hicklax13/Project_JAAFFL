"""Dependency-light smoke test: the package imports without optional extras."""

import jaaffl


def test_version_exposed() -> None:
    assert isinstance(jaaffl.__version__, str)
    assert jaaffl.__version__
