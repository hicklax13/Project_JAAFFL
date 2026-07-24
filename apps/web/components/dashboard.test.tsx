/**
 * Dashboard integration (Stage-6 DoD): the war room renders a live Recommendation (best +
 * decomposition), the on-screen total reconstructs from ScoreComponents, and the 404/409/503
 * degraded states render honestly. The backend is injected — no server, no network.
 */
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  type DraftBoardState,
  type LeagueSettings,
  LeagueSettingsSchema,
  type Recommendation,
} from "@jaaffl/shared";

import type { AnalyticsResult, RecsHandlers, RecommendationResult, StateResult } from "../lib/api";
import { Dashboard } from "./dashboard";
import type { DraftRoomApi } from "./use-recs";

// components reconstruct to 41.2 at kappa=0.6: 32.4 + 0.6*15.0 - 2.1 + 2.0 + (-0.1) = 41.2
const REC: Recommendation = {
  league_id: "cbs-local",
  as_of_overall_pick: 27,
  reasoning: "R3P3 · floor-tilt λ=+0.2 · κ=0.6 · α=0.4 · flex_split=8RB/4WR (EngineParams v1.0.0)",
  ranked: [
    {
      player_id: "p1",
      name: "James Cook",
      position: "RB",
      nfl_team: "BUF",
      bye_week: 7,
      score: 41.2,
      next_turn_availability: 0.18,
      tier: 3,
      rationale: "Last elite anchor-RB before the cliff.",
      components: {
        mlv: 32.4,
        vona: 15.0,
        risk_penalty: 2.1,
        cliff_bonus: 2.0,
        sigma: 40,
        floor: 200,
        ceiling: 300,
        replacement_baseline: 118,
        modifiers: { bye_stack: -0.1 },
      },
    },
    { player_id: "p2", name: "Drake London", position: "WR", nfl_team: "ATL", score: 37.8, next_turn_availability: 0.41, tier: 4 },
  ],
};

const LEAGUE: LeagueSettings = LeagueSettingsSchema.parse({
  league_id: "cbs-local",
  team_count: 12,
  draft_type: "snake",
  roster_slots: [
    { slot: "QB", eligible_positions: ["QB"], count: 1, starting: true },
    { slot: "RB", eligible_positions: ["RB"], count: 1, starting: true },
    { slot: "WR", eligible_positions: ["WR"], count: 3, starting: true },
    { slot: "WR/RB", eligible_positions: ["WR", "RB"], count: 1, starting: true },
    { slot: "TE", eligible_positions: ["TE"], count: 1, starting: true },
    { slot: "K", eligible_positions: ["K"], count: 1, starting: true },
    { slot: "DST", eligible_positions: ["DST"], count: 1, starting: true },
    { slot: "BENCH", eligible_positions: ["QB", "RB", "WR", "TE"], count: 8, starting: false },
  ],
});

function fakeApi(
  opts: {
    recResult?: RecommendationResult;
    league?: LeagueSettings;
    stateResult?: StateResult;
    analyticsResult?: AnalyticsResult;
  } = {},
): {
  api: Partial<DraftRoomApi>;
  captured: { handlers?: RecsHandlers };
} {
  const captured: { handlers?: RecsHandlers } = {};
  const api: Partial<DraftRoomApi> = {
    getRecommendation: async () => opts.recResult ?? { status: 200, recommendation: null },
    fetchLeague: async () => opts.league ?? null,
    fetchState: async () => opts.stateResult ?? { status: 200, state: null },
    // Default to the honest "engine warming" shape — never a real fetch, so the suite stays
    // hermetic (network-free) whether or not a backend happens to be listening on 127.0.0.1:8788.
    fetchAnalytics: async () => opts.analyticsResult ?? { status: 503, analytics: null },
    subscribeRecs: (_id, handlers) => {
      captured.handlers = handlers;
      handlers.onStatus?.("live");
      return () => {};
    },
  };
  return { api, captured };
}

describe("Dashboard", () => {
  it("renders a hydrated recommendation whose displayed total reconstructs from components", async () => {
    const { api } = fakeApi({ recResult: { status: 200, recommendation: REC }, league: LEAGUE });
    render(<Dashboard leagueId="cbs-local" api={api} />);

    const total = await screen.findByTestId("why-total");
    expect(total).toHaveTextContent("41.2");
    expect(screen.getByLabelText(/reconstructs/i)).toBeInTheDocument();
    expect(screen.getAllByText("James Cook").length).toBeGreaterThan(0);
    // verbatim roster rail (§6.9): the WR/RB flex is WR-or-RB only
    expect(screen.getByText(/WR or RB only/i)).toBeInTheDocument();
  });

  it("updates on a WS /recs/ws push without a page reload", async () => {
    const { api, captured } = fakeApi({ recResult: { status: 200, recommendation: null }, league: LEAGUE });
    render(<Dashboard leagueId="cbs-local" api={api} />);
    await screen.findByText(/appear here on the next pick/i);
    act(() => captured.handlers?.onRecommendation(REC));
    expect(await screen.findByTestId("why-total")).toHaveTextContent("41.2");
  });

  it("shows the engine-warming-up state on a 503 hydrate", async () => {
    const { api } = fakeApi({ recResult: { status: 503, recommendation: null } });
    render(<Dashboard leagueId="cbs-local" api={api} />);
    expect(await screen.findByText(/warming up/i)).toBeInTheDocument();
  });

  it("shows the unknown-league state on a 404 hydrate", async () => {
    const { api } = fakeApi({ recResult: { status: 404, recommendation: null } });
    render(<Dashboard leagueId="nope" api={api} />);
    expect(await screen.findByText(/unknown league/i)).toBeInTheDocument();
  });

  it("renders the draft board + pick log from GET /state", async () => {
    const boardState: DraftBoardState = {
      league_id: "cbs-local",
      current_overall_pick: 2,
      on_the_clock_team_id: "T2",
      my_team_id: "T1",
      complete: false,
      picks: [
        {
          overall: 1,
          round: 1,
          pick_in_round: 1,
          team_id: "T1",
          player_id: "gsis:cmc",
          name: "Christian McCaffrey",
          position: "RB",
          nfl_team: "SF",
        },
      ],
    };
    const { api } = fakeApi({
      recResult: { status: 200, recommendation: null },
      league: LEAGUE,
      stateResult: { status: 200, state: boardState },
    });
    render(<Dashboard leagueId="cbs-local" api={api} />);
    expect(await screen.findByLabelText("Pick log")).toBeInTheDocument();
    expect(screen.getAllByText("Christian McCaffrey").length).toBeGreaterThan(0);
  });
});
