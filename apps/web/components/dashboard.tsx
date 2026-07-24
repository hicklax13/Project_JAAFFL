"use client";

import { useEffect, useReducer, type ReactElement } from "react";

import { DEFAULT_LEAGUE_ID } from "../lib/api";
import { BoardPanel } from "./board-panel";
import { SurvivalPanel, TierLadder } from "./charts";
import { ReasoningLine, RosterRail, ScoringPanel, SettingsBadges, StatusBanner } from "./league-panels";
import { playerName, RecommendationBanner, TopFive } from "./recommendation-banner";
import { ThemeToggle } from "./theme-toggle";
import { type DraftRoomApi, useDraftRoom } from "./use-recs";

export interface DashboardProps {
  leagueId?: string;
  /** Injectable backend seam for tests; defaults to the real localhost client. */
  api?: Partial<DraftRoomApi>;
}

/**
 * The war room (§6.4). Owns the live /recs/ws subscription (via useDraftRoom) and lays out the
 * recommendation + its decomposed "why", the verbatim league settings, roster, and the v1-lite
 * analytics. Read-only: it performs NO CBS write and talks only to 127.0.0.1:8788.
 */
export function Dashboard({ leagueId = DEFAULT_LEAGUE_ID, api }: DashboardProps): ReactElement {
  const state = useDraftRoom(leagueId, api);
  const [, tick] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const rec = state.recommendation;
  const best = rec?.ranked[0] ?? null;
  const syncedAgoMs = state.lastUpdated == null ? null : Date.now() - state.lastUpdated;

  return (
    <div className="draft-room">
      <header className="dr-top">
        <div className="brandmark">
          <span className="word">JAAFFL</span>
          <span className="eyebrow">Draft room</span>
        </div>
        <SettingsBadges league={state.league} />
        <div className="dr-top-right">
          <StatusBanner
            socket={state.socket}
            hydrateError={state.hydrateError}
            syncedAgoMs={syncedAgoMs}
            hasRec={best != null}
          />
          <ThemeToggle />
        </div>
      </header>

      {/* Polite live region: announce the pushed pick WITHOUT moving focus under the clock. */}
      <p className="sr-only" role="status" aria-live="polite">
        {best
          ? `Recommended: ${playerName(best)}${best.position ? `, ${best.position}` : ""}, score ${best.score.toFixed(1)}`
          : ""}
      </p>

      <div className="dr-grid">
        <aside className="dr-rail" aria-label="Roster and format">
          <RosterRail league={state.league} />
        </aside>

        <main className="dr-main">
          {best ? (
            <>
              <RecommendationBanner best={best} reasoning={rec?.reasoning} />
              <ReasoningLine reasoning={rec?.reasoning} />
              <TopFive ranked={rec?.ranked ?? []} />
            </>
          ) : (
            <section className="reco card waiting" aria-live="polite">
              <span className="eyebrow">Watching the board</span>
              <p className="muted">
                The recommendation and its decomposed “why” appear here on the next pick.
              </p>
            </section>
          )}
        </main>

        <aside className="dr-analytics" aria-label="Draft analytics">
          <SurvivalPanel ranked={rec?.ranked ?? []} />
          <TierLadder ranked={rec?.ranked ?? []} />
          <ScoringPanel league={state.league} />
        </aside>
      </div>

      <BoardPanel state={state.boardState} />

      <footer className="dr-foot">
        <span className="muted">
          Personal, local-first, $0 assistant · text-only · no CBS writes · no proven optimal
          live-snake-draft solver exists — efficacy is offline-validated. Forward-year figures are
          ESTIMATED.
        </span>
      </footer>
    </div>
  );
}
