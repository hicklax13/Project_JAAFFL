"use client";

import { useEffect, useReducer, useRef } from "react";

import type { LeagueSettings, Recommendation } from "@jaaffl/shared";

import {
  fetchLeague as realFetchLeague,
  getRecommendation as realGetRecommendation,
  type RecommendationResult,
  type RecsSocketState,
  subscribeRecs as realSubscribeRecs,
} from "../lib/api";
import type { HydrateError } from "./league-panels";

/** The backend seam — real by default, injectable so the dashboard is tested without a server. */
export interface DraftRoomApi {
  subscribeRecs: typeof realSubscribeRecs;
  getRecommendation: (leagueId: string) => Promise<RecommendationResult>;
  fetchLeague: (leagueId: string) => Promise<LeagueSettings | null>;
}

const REAL_API: DraftRoomApi = {
  subscribeRecs: realSubscribeRecs,
  getRecommendation: realGetRecommendation,
  fetchLeague: realFetchLeague,
};

export interface DraftRoomState {
  recommendation: Recommendation | null;
  league: LeagueSettings | null;
  socket: RecsSocketState;
  hydrateError: HydrateError;
  lastUpdated: number | null;
}

type Action =
  | { type: "rec"; recommendation: Recommendation; at: number }
  | { type: "hydrate"; result: RecommendationResult; at: number }
  | { type: "league"; league: LeagueSettings | null }
  | { type: "socket"; socket: RecsSocketState };

function statusToError(status: number): HydrateError {
  if (status === 404) return "unknown-league";
  if (status === 409) return "not-started";
  if (status === 503) return "warming-up";
  if (status === 0) return "offline";
  return null;
}

function reducer(state: DraftRoomState, action: Action): DraftRoomState {
  switch (action.type) {
    case "rec":
      return {
        ...state,
        recommendation: action.recommendation,
        hydrateError: null,
        lastUpdated: action.at,
      };
    case "hydrate":
      return {
        ...state,
        recommendation: action.result.recommendation ?? state.recommendation,
        hydrateError: statusToError(action.result.status),
        lastUpdated: action.result.recommendation ? action.at : state.lastUpdated,
      };
    case "league":
      return { ...state, league: action.league };
    case "socket":
      return { ...state, socket: action.socket };
  }
}

const INITIAL: DraftRoomState = {
  recommendation: null,
  league: null,
  socket: "connecting",
  hydrateError: null,
  lastUpdated: null,
};

/**
 * Own the live draft-room data: hydrate once over REST (mapping 404/409/503 to honest states),
 * then track WS /recs/ws pushes (snapshot + rec) with the socket's connection state. The socket
 * is opened in an effect and closed on cleanup (React 19 / StrictMode-safe).
 */
export function useDraftRoom(leagueId: string, apiOverride?: Partial<DraftRoomApi>): DraftRoomState {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const apiRef = useRef<DraftRoomApi>({ ...REAL_API, ...apiOverride });

  useEffect(() => {
    const api = apiRef.current;
    let active = true;

    void api.getRecommendation(leagueId).then((result) => {
      if (active) dispatch({ type: "hydrate", result, at: Date.now() });
    });
    void api.fetchLeague(leagueId).then((league) => {
      if (active) dispatch({ type: "league", league });
    });

    const unsubscribe = api.subscribeRecs(leagueId, {
      onRecommendation: (recommendation) =>
        active && dispatch({ type: "rec", recommendation, at: Date.now() }),
      onStatus: (socket) => active && dispatch({ type: "socket", socket }),
    });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [leagueId]);

  return state;
}
