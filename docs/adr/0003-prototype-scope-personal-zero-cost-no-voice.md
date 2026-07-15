# 3. Prototype scope: personal-use, $0 out-of-pocket, no voice

Date: 2026-07-15

## Status

Accepted

## Context

The owner set explicit scope for the current phase. This ADR pins those constraints so the
scaffold and near-term work don't drift toward premature cost or complexity.

## Decision

For the current prototype phase:

1. **Personal use only.** Not a commercial or shared product. CBS data is used solely from
   the owner's own authenticated session (see `../legal-and-compliance.md`).
2. **$0 out-of-pocket besides AI usage.** The prototype runs on free data only:
   - **nflverse / nflfastR** for historical NFL stats (free, no key), and
   - **CBS's own on-page** projections / rankings / ADP, read from the authenticated session
     via the extension.
   All paid providers (**FantasyPros Premium**, **SportsDataIO**, **Sportradar**) are
   **opt-in and off by default**. The only allowed recurring cost is AI credits for the
   assistant.
3. **No voice.** The AI assistant is **text-only**. The OpenAI Realtime / voice capability
   is out of scope for the prototype.

## Consequences

- Default provider config enables nflverse only; FantasyPros and commercial feeds are
  gated behind `JAAFFL_ENABLE_*` flags that default to `false`.
- With no paid projection feed, current-season projection/ADP quality in the $0 tier leans
  on CBS on-page data plus nflverse-derived historical features. This is an accepted
  limitation of the free tier; enabling FantasyPros later improves it without code changes.
- No Realtime/voice dependencies, endpoints, or UI are built. `jaaffl.assistant` targets the
  Responses API (text) only.
- These are **prototype-phase** constraints. Revisiting them (e.g., to commercialize) means
  a new ADR that supersedes this one, plus the compliance review noted in ADR 0002.
