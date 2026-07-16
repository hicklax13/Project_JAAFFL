"""Stage 4 of the engine: Boris-Chen positional tiers + cliff bonuses (§3.6).

Tiers are **interpretation and a guard rail**, not an optimizer. ``assign_tiers`` fits a 1-D
``sklearn.mixture.GaussianMixture`` on each position's ECR, choosing the component count by BIC
(≤ ``max_tiers_per_pos``) and ordering components by mean ECR → 1-indexed tiers (tier 1 = best).
``cliff_bonuses`` flags the last player before a talent gap: the drop from a tier's weakest player
to the best of the next tier down. Both are precomputed into ``DraftContext`` (ECR is static
pre-draft); the hot path only reads ``context.cliff_bonus[p]``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from jaaffl.domain import Position


def assign_tiers(
    ecr: Mapping[str, float],
    position: Mapping[str, Position],
    *,
    max_tiers_per_pos: int = 8,
    random_state: int = 0,
) -> dict[str, int]:
    """Per position: fit GaussianMixture on 1-D ECR, pick component count by BIC, order by mean
    ECR → contiguous 1-indexed tiers. Deterministic for a fixed ``random_state``."""
    import numpy as np
    from sklearn.mixture import GaussianMixture

    by_pos: dict[Position, list[str]] = defaultdict(list)
    for pid, pos in position.items():
        if pid in ecr:
            by_pos[pos].append(pid)

    tiers: dict[str, int] = {}
    for pids in by_pos.values():
        values = np.asarray([ecr[p] for p in pids], dtype=float).reshape(-1, 1)
        distinct = len({float(v) for v in values.ravel()})
        # Regularize model selection: BIC decreases monotonically on tiny, hyper-separated pools
        # (it would over-split to one tier per player). Require ~3 players per tier so tiers stay
        # meaningful; on realistic position pools (~40+ ECRs) BIC finds its own minimum below this.
        max_k = min(max_tiers_per_pos, distinct, max(1, len(pids) // 3))
        if max_k <= 1:  # one player / one distinct ECR / too few to tier → a single tier
            for pid in pids:
                tiers[pid] = 1
            continue

        best_gm: GaussianMixture | None = None
        best_bic = float("inf")
        for k in range(1, max_k + 1):
            gm = GaussianMixture(n_components=k, random_state=random_state, n_init=1)
            gm.fit(values)
            bic = gm.bic(values)
            if bic < best_bic:
                best_bic, best_gm = bic, gm

        assert best_gm is not None
        labels = best_gm.predict(values)
        means = best_gm.means_.ravel()
        # Contiguous tiers over ONLY the components that were actually assigned points, ordered by
        # mean ECR ascending (so a gap in used components never leaves a hole in the tier numbers).
        used = sorted({int(c) for c in labels}, key=lambda c: means[c])
        comp_to_tier = {comp: rank + 1 for rank, comp in enumerate(used)}
        for pid, label in zip(pids, labels, strict=True):
            tiers[pid] = comp_to_tier[int(label)]
    return tiers


def cliff_bonuses(
    tiers: Mapping[str, int],
    mlv: Mapping[str, float],
    position: Mapping[str, Position],
) -> dict[str, float]:
    """CliffBonus_p = MLV_p − MLV(best player in the next tier down at pos(p)) if p is the WEAKEST
    (lowest-MLV) player in its tier, else 0.0 (design §6.C.6). The bottom tier's last player has no
    tier below → 0.0. Clamped to ≥ 0 — a cliff is urgency, never a penalty (Score adds α·Cliff).
    """
    bonuses: dict[str, float] = dict.fromkeys(tiers, 0.0)

    by_pos_tier: dict[tuple[Position, int], list[str]] = defaultdict(list)
    for pid, tier in tiers.items():
        by_pos_tier[(position[pid], tier)].append(pid)

    for (pos, tier), members in by_pos_tier.items():
        next_tier = by_pos_tier.get((pos, tier + 1))
        if not next_tier:  # bottom tier at this position → no cliff below
            continue
        last_in_tier = min(members, key=lambda p: mlv[p])  # weakest of this tier
        best_next = max(mlv[q] for q in next_tier)
        bonuses[last_in_tier] = max(0.0, mlv[last_in_tier] - best_next)
    return bonuses
