"""End-to-end regression: real-shaped CBS draft-socket events -> fold -> resolve -> engine mask.

Manually verified against a FULL real record-mode capture (165 real picks, 6.8 MB, git-ignored
per docs/research/cbs-draft-protocol.md): parse.ts emits an ID-only pick_made (player_id=
"cbs:<id>") plus a trailing "ticker" draft_state event with no ``picks`` key, for nearly every
frame. This test pins the seam end to end with data shaped exactly like the committed golden
fixtures (apps/extension/tests/fixtures/cbs/picks-completed.{autopick,final}.json, values pinned
by apps/extension/tests/parse.test.ts) so it never needs the raw capture or a network/sqlite
crosswalk:

1. fold_state must not lose a pick to a trailing ticker-only draft_state (dedicated regression:
   test_ingest_log.py::test_fold_draft_state_ticker_does_not_wipe_previously_folded_picks).
2. resolve_pick_ids must turn a linked "cbs:<id>" into its canonical id, and leave an unlinked
   one untouched (never guessed, never dropped) -- test_resolve.py covers this in isolation.
3. jaaffl.engine.recommend must then actually exclude the resolved, drafted player from the
   candidate pool while keeping an undrafted one -- test_recommend.py covers this in isolation,
   but always with an ALREADY-canonical player_id; nothing previously chained resolve_pick_ids's
   output into recommend()'s mask, which is exactly the seam the real capture exercised.
"""

from __future__ import annotations

from jaaffl.domain import Position
from jaaffl.engine.recommend import recommend
from jaaffl.ingest.log import LoggedEvent, fold_state
from jaaffl.ingest.resolve import resolve_pick_ids
from tests.engine_fixtures import engine_params, jaaffl_settings, make_context


def _logged(event_type: str, data: dict, *, seq: int, pick: int | None = None) -> LoggedEvent:
    return LoggedEvent(
        seq=seq,
        league_id="cbs-live",
        event_type=event_type,
        pick_number=pick,
        data=data,
        source="ws",
        captured_at="2026-07-25T00:00:00.000Z",
    )


def _real_shaped_events() -> list[LoggedEvent]:
    """Two ID-only picks, each immediately followed by a ticker-only draft_state -- the same
    [pick_made(s)..., draft_state] emission order ``parseNetworkFrame`` produces per frame, and
    the exact shape of picks-completed.autopick.json (pick 1) played twice in miniature."""
    return [
        _logged(
            "pick_made",
            {
                "overall": 1,
                "round": 1,
                "pick_in_round": 1,
                "team_id": "1",
                "pick_source": "autopick",
                "player_id": "cbs:3162723",
                "cbs_player_id": "3162723",
            },
            seq=1,
            pick=1,
        ),
        _logged(
            "draft_state",
            {
                "current_overall_pick": 2,
                "round": 1,
                "on_the_clock_team_id": "2",
                "on_deck_team_id": "3",
            },
            seq=2,
        ),
        _logged(
            "pick_made",
            {
                "overall": 2,
                "round": 1,
                "pick_in_round": 2,
                "team_id": "2",
                "pick_source": "userpick",
                "player_id": "cbs:9999999",  # deliberately has no crosswalk link below
                "cbs_player_id": "9999999",
            },
            seq=3,
            pick=2,
        ),
        _logged(
            "draft_state",
            {
                "current_overall_pick": 3,
                "round": 1,
                "on_the_clock_team_id": "3",
                "on_deck_team_id": "4",
            },
            seq=4,
        ),
    ]


def test_real_shaped_cbs_events_survive_fold_resolve_and_mask() -> None:
    events = _real_shaped_events()

    # 1) fold: both picks survive their trailing ticker draft_state.
    state = fold_state(events)
    assert [p.overall for p in state.picks] == [1, 2]
    assert [p.player_id for p in state.picks] == ["cbs:3162723", "cbs:9999999"]

    # 2) resolve: only the first id has a crosswalk link; the second degrades honestly.
    resolved = resolve_pick_ids(
        state,
        events,
        resolver=lambda *a: None,
        cbs_resolver=lambda cbs_id: {"3162723": "gsis:gibbs"}.get(cbs_id),
    )
    assert resolved.picks[0].player_id == "gsis:gibbs"
    assert resolved.picks[1].player_id == "cbs:9999999"  # unresolved: kept, never dropped/guessed

    # 3) mask: the resolved+drafted player must vanish from the candidate pool; an undrafted
    # real-shaped candidate must remain. The still-cbs:-prefixed pick can never match a
    # candidate's canonical id either, so it is (necessarily, and separately) never masked --
    # exactly the "unresolved => not masked" correctness gap resolve_pick_ids's docstring warns
    # about, not re-asserted here (test_resolve.py owns that contract).
    settings = jaaffl_settings(league_id="cbs-live", draft_order=[str(i) for i in range(1, 13)])
    ctx = make_context(
        [
            {"pid": "gsis:gibbs", "pos": Position.RB, "mu": 300.0, "adp": 1.0},
            {"pid": "gsis:other-rb", "pos": Position.RB, "mu": 250.0, "adp": 5.0},
        ],
        params=engine_params(candidate_cap=100),
        settings=settings,
    )
    rec = recommend(resolved, ctx, ctx.params)
    ranked_ids = {p.player_id for p in rec.ranked}
    assert "gsis:gibbs" not in ranked_ids  # drafted (and resolved) -> masked out
    assert "gsis:other-rb" in ranked_ids  # undrafted -> still a candidate
