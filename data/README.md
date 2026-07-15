# data/

Local-first warehouse root (`JAAFFL_DATA_DIR`, default `./data`). Holds the DuckDB database,
Parquet extracts, SQLite app/league state, and persisted CBS league/draft snapshots.

**Everything here except this README and `.gitkeep` is git-ignored** — generated data and
league snapshots stay on your machine and are never committed (see `.gitignore` and
`docs/legal-and-compliance.md`).
