"""Deterministic prose for a RecommendedPick's ScoreComponents (Stage 7 [v1-lite]).

The key-free core of the ``explain_recommendation`` tool: no OpenAI, no network — just the additive
Score(p) decomposition (design §10.3) rendered as a sentence a human can read. Score reconstructs as
``mlv + κ·max(0, vona) − risk_penalty + cliff_bonus + Σ modifiers``; this narrates each term.
"""

from __future__ import annotations

from jaaffl.config import EngineParams
from jaaffl.domain import RecommendedPick


def explain_pick(pick: RecommendedPick, params: EngineParams | None = None) -> str:
    """Return a prose explanation of ``pick`` from its :class:`ScoreComponents`.

    Falls back to a bare score line when the pick carries no decomposition (pre-engine payloads),
    so it never raises. ``params`` (κ, α) are cited when given — the weights are part of the "why".
    """
    who = pick.name or pick.player_id
    if pick.position is not None:
        team = f", {pick.nfl_team}" if pick.nfl_team else ""
        who = f"{who} ({pick.position.value}{team})"
    lead = f"{who} scores {pick.score:.1f}"
    if pick.tier is not None:
        lead += f" (tier {pick.tier})"
    lead += "."

    c = pick.components
    if c is None:
        return f"{lead} {pick.rationale}".rstrip() if pick.rationale else lead

    posname = pick.position.value if pick.position is not None else "player"
    sentences = [
        lead,
        f"Its marginal lineup value is {c.mlv:.1f} points over a replacement {posname} "
        f"(baseline {c.replacement_baseline:.0f}).",
    ]

    if c.vona > 0:
        kappa = f", κ={params.kappa:g}" if params else ""
        sentences.append(
            f"High urgency (VONA {c.vona:.1f}{kappa}): a comparable {posname} likely "
            f"won't survive to your next pick."
        )
    else:
        sentences.append(
            f"Low urgency: comparable {posname} value should survive to your next pick."
        )

    if c.cliff_bonus > 0:
        alpha = f" (α={params.alpha:g})" if params else ""
        sentences.append(
            f"A tier cliff adds {c.cliff_bonus:.1f}{alpha} — the talent drops off after this tier."
        )

    direction = "down" if c.risk_penalty > 0 else "up"
    sentences.append(
        f"Risk-adjusted {direction} {abs(c.risk_penalty):.1f} for volatility "
        f"(σ {c.sigma:.0f}; floor {c.floor:.0f} / ceiling {c.ceiling:.0f})."
    )

    mods = {name: value for name, value in c.modifiers.items() if value}
    if mods:
        parts = ", ".join(f"{name} {value:+.1f}" for name, value in mods.items())
        sentences.append(f"Situational adjustments: {parts}.")

    if pick.next_turn_availability is not None:
        sentences.append(
            f"~{round(pick.next_turn_availability * 100)}% to survive to your next pick."
        )

    return " ".join(sentences)
