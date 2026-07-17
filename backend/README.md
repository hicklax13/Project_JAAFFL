# backend — JAAFFL Python companion service

FastAPI service bound to localhost. It receives normalized draft events from the browser
extension, persists league snapshots, runs the draft engine, and serves recommendations to
the extension overlay and the web dashboard.

## Layout (`src/jaaffl/`)

| Package     | Stage | Responsibility                                                        |
| ----------- | ----- | -------------------------------------------------------------------- |
| `domain`    | —     | Pydantic models — the shared vocabulary (mirror of `packages/shared`)|
| `config`    | —     | Typed settings from environment (`.env`)                             |
| `api`       | 1     | HTTP/WebSocket endpoints; ingest events, serve recommendations       |
| `ingest`    | 1–2   | Normalize raw CBS payloads into domain events                        |
| `league`    | 2     | CBS scoring parser, replacement (VORP) values, positional scarcity   |
| `data`      | 3     | DuckDB/SQLite/Parquet warehouse + cross-source ID crosswalks         |
| `providers` | 4     | Provider protocol + adapters (nflverse free; others opt-in)          |
| `engine`    | 5     | Projection ensemble, opponent model, simulation, optimizer           |
| `assistant` | 7     | Typed function tools for the text-only AI assistant                  |

## Develop

```bash
python -m pip install -e '.[dev]'   # or: uv pip install -e '.[dev]'
# add extras as you reach each stage: '.[data]', '.[engine]', '.[assistant]', or '.[all]'

python -m jaaffl.api                # run the companion service (127.0.0.1:8788)
ruff check . && ruff format --check .
pytest -q
```

## Conventions

- `jaaffl.engine` depends on the `jaaffl.providers` **protocol**, never on a concrete
  adapter. Sources stay swappable and paid feeds stay off by default.
- Domain shapes here and the Zod schemas in `packages/shared` change together.
- See [`../docs/legal-and-compliance.md`](../docs/legal-and-compliance.md) before enabling
  any provider or the unofficial CBS adapter.
