# @jaaffl/extension — CBS sync layer (Manifest V3)

Runs **only** on CBS fantasy league and draft pages, inside the user's own authenticated
session. It reads league settings and live pick events, normalizes them to the
`@jaaffl/shared` schema, and streams them to the localhost companion service. A thin overlay
(rendered in a shadow DOM so CBS page styles can't leak in) shows in-draft guidance.

## Structure

```
manifest.json                 MV3 manifest — narrowly scoped host permissions
src/background/               service worker (lifecycle)
src/content/                  content scripts (league + draft room)
src/overlay/                  in-page overlay (shadow DOM)
src/lib/parse.ts              CBS DOM/network → normalized events (Stage 1–2)
src/lib/transport.ts          send normalized events to the backend
```

## Status & the first Stage-1 task

The TypeScript **typechecks** today (`pnpm --filter @jaaffl/extension typecheck`), and the
event/transport/overlay wiring is in place. What's intentionally **not** wired yet:

1. **A bundler** to emit a loadable `dist/` from `manifest.json` + `src/` (the manifest
   references `.ts` entry points). Recommended: `@crxjs/vite-plugin` or a small `esbuild`
   build. This is the first Stage-1 implementation step.
2. **The CBS parsers** in `src/lib/parse.ts` (`parseLeagueSettings`, `parseDraftEvent`) —
   currently return `null` until the live DOM/network shapes are mapped.

## Compliance

Keep permissions minimal (currently just `storage` + narrowly-scoped host permissions; no
cookies, no broad `webRequest`). This extension only ever runs in the user's own session —
see [`../../docs/legal-and-compliance.md`](../../docs/legal-and-compliance.md).
