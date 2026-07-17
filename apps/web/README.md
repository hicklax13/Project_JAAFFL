# @jaaffl/web — analytics dashboard (Next.js)

The richer analytics surface (App Router). Reads from the localhost companion service and
shares wire types with the extension via `@jaaffl/shared`.

```bash
pnpm --filter @jaaffl/web dev        # http://localhost:3000
```

Planned panels (Stage 6): draft board + pick log (AG Grid Community), projection
distributions and trends (ECharts), manager-tendency panels, and scenario comparison. They
populate once the data tiers (Stage 4) and engine (Stage 5) are wired. Set
`NEXT_PUBLIC_API_BASE_URL` if the backend isn't on the default `http://127.0.0.1:8788`.
