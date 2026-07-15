# @jaaffl/shared

The JS/TS side of the wire contract. These Zod schemas define the normalized shapes that the
extension sends to the backend and the dashboard reads back. Field names are **snake_case** to
match the JSON the Python backend (`jaaffl.domain`) expects.

> Change a shape here and in `backend/src/jaaffl/domain/models.py` **together** — they are two
> encodings of one contract.

## Exports

- `events.ts` — `DraftEvent`, `DraftState`, `DraftPick`, `DraftEventType`
- `league.ts` — `LeagueSettings`, `RosterSlot`, `ScoringRule`, `Position`
- `recommendation.ts` — `Recommendation`, `RecommendedPick`

Consumed as an internal source package (no build step): bundlers/`tsc` read `src/` directly.
