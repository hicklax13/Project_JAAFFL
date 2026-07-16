# data/

Local-first warehouse root (`JAAFFL_DATA_DIR`, default `./data`). **Everything here except
this README and `.gitkeep` is git-ignored** — generated data and league snapshots stay on
your machine and are never committed (see `.gitignore` and `docs/legal-and-compliance.md`).

## Three-store role split (plan §2.2–§2.5)

Each store is chosen for the *durability class* of the data it owns:

| Store | File(s) | Owns | Rebuildable? |
|---|---|---|---|
| **SQLite** (ACID) | `app.sqlite` (+ `-wal`, `-shm`) | append-only `draft_event_log`, `league_snapshots`, `players`, `id_crosswalk`, `manager_tendencies`, `schema_migrations` | **No** — the crown jewels. The only unrecoverable loss. |
| **Parquet** | `parquet/nflverse/*`, `parquet/ffc/*`, `snapshots/draft_*/*` | raw nflverse / FFC pulls, per-draft exports | **Yes** — re-pull from upstream |
| **DuckDB** | `warehouse.duckdb` | materialized `projections`, `adp`, analytics | **Yes** — `make warehouse` rebuilds it |

The organizing principle: of everything the system holds, only the live pick stream is
unrebuildable, so it — and only it — gets ACID durability (WAL + `synchronous=FULL`).

## Disposability

`warehouse.duckdb` and `parquet/` are **disposable**. `make warehouse` rebuilds
`warehouse.duckdb` from Parquet + SQLite; deleting it is never data loss. Deleting
`app.sqlite` **is** — it holds the live draft-event log and the locally-owned CBS snapshots
that no free feed can reconstruct.

Schema is kept graduation-friendly (§2.9): the JSON payload columns map 1:1 to PostgreSQL
`jsonb` and the monotonic-`seq` log maps 1:1 to a Redis Stream, so this can graduate to
Postgres + Redis Streams later without changing callers.
