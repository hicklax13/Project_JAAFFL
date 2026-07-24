"use client";

import type { ReactElement } from "react";

import type { DraftBoardState } from "@jaaffl/shared";

import { toDraftBoard } from "../lib/board";

/**
 * The draft board + pick-log (§6.4 analytics). Renders the folded `GET /state` view: a
 * round × team grid (columns self-order to the draft slots — see toDraftBoard) plus a newest-first
 * pick-log ticker. Read-only; a name-only paste pick that never resolved to a canonical id still
 * shows, so the board never silently drops a drafted player.
 */
export function BoardPanel({ state }: { state: DraftBoardState | null }): ReactElement {
  const board = toDraftBoard(state?.picks ?? []);
  const onClock = state?.on_the_clock_team_id ?? null;
  const myTeam = state?.my_team_id ?? null;

  if (board.log.length === 0) {
    return (
      <section className="board card" aria-label="Draft board">
        <span className="eyebrow">Draft board</span>
        <p className="muted">Picks appear here as the draft unfolds.</p>
      </section>
    );
  }

  return (
    <section className="board card" aria-label="Draft board">
      <span className="eyebrow">Draft board</span>
      <div className="board-scroll">
        <table className="board-grid">
          <thead>
            <tr>
              <th scope="col" className="rnd" aria-label="Round">
                R
              </th>
              {board.teams.map((team) => (
                <th scope="col" key={team} className={teamHeaderClass(team, onClock, myTeam)}>
                  {team}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {board.rounds.map((round) => (
              <tr key={round}>
                <th scope="row" className="rnd">
                  {round}
                </th>
                {board.teams.map((team) => {
                  const p = board.cell(round, team);
                  return (
                    <td key={team} data-pos={p?.position ?? undefined}>
                      {p ? (
                        <span className="cell">
                          <span className="nm">{p.name ?? p.player_id ?? "—"}</span>
                          {p.position ? <span className="ps">{p.position}</span> : null}
                        </span>
                      ) : null}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <span className="eyebrow">Pick log</span>
      <ol className="pick-log" aria-label="Pick log">
        {board.log.slice(0, 24).map((p) => (
          <li key={p.overall}>
            <span className="pk">
              R{p.round}.{String(p.pick_in_round).padStart(2, "0")}
            </span>
            <span className="tm">{p.team_id}</span>
            <span className="nm">{p.name ?? p.player_id ?? "—"}</span>
            {p.position ? (
              <span className="ps">
                {p.position}
                {p.nfl_team ? ` · ${p.nfl_team}` : ""}
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function teamHeaderClass(team: string, onClock: string | null, myTeam: string | null): string | undefined {
  const cls: string[] = [];
  if (team === onClock) cls.push("on-clock");
  if (team === myTeam) cls.push("mine");
  return cls.length ? cls.join(" ") : undefined;
}
