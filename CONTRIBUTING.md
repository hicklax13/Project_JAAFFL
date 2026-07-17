# Contributing

## Prerequisites

- Python ≥ 3.11 (3.12 recommended). [`uv`](https://docs.astral.sh/uv/) recommended.
- Node ≥ 22, pnpm ≥ 10.

## Setup

```bash
cp .env.example .env
make setup      # backend (editable install, dev extras) + pnpm workspace install
```

## Everyday tasks

| Command            | What it does                                             |
| ------------------ | -------------------------------------------------------- |
| `make backend-dev` | Run the FastAPI companion service (127.0.0.1:8788)       |
| `make web-dev`     | Run the Next.js dashboard                                |
| `make ext-dev`     | Build the extension in watch mode                        |
| `make lint`        | Ruff (Python) + ESLint/Prettier (JS)                     |
| `make fmt`         | Auto-format Python and JS                                |
| `make test`        | Pytest (Python) + workspace tests                        |

## Conventions

- **Shared contracts change together.** If you edit a normalized event/league/recommendation
  shape, update **both** `packages/shared` (Zod) and `jaaffl.domain` (Pydantic) in the same
  change, and note it in the PR.
- **Engine depends on protocols, not adapters.** Never import a concrete provider
  (`jaaffl.providers.nflverse`, etc.) from `jaaffl.engine`. Depend on
  `jaaffl.providers.base` and resolve concrete providers through the registry/config.
- **New data source?** Implement the provider protocol, register it, and add a feature flag
  in `.env.example` + `jaaffl.config`. Default new/commercial providers to **off**.
- **Compliance is not optional.** Anything touching CBS must stay within
  [`docs/legal-and-compliance.md`](docs/legal-and-compliance.md): user-authorized session
  only, personal use, no commercial scraping. The unofficial CBS API adapter ships disabled.
- Keep Python typed (`mypy` clean where practical) and formatted with Ruff. Keep JS strict
  (`tsc --noEmit` clean) and formatted with Prettier.

## Architecture decisions

Significant, hard-to-reverse choices are recorded as ADRs in [`docs/adr/`](docs/adr/).
Add a new numbered ADR when you make one.
