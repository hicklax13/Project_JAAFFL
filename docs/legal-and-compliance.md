# Legal & compliance guardrails

The research report's clearest finding: **CBS integration is the gating risk**, and legal /
platform risk matters as much as code risk. This file distills the constraints the codebase
is designed to respect. It is engineering guidance, not legal advice — consult a
professional before any commercial use.

## CBS terms of use

- CBS's general terms permit access for **personal, non-commercial** purposes unless
  otherwise authorized in writing.
- CBS's acceptable-use terms prohibit unauthorized spidering, scraping, data mining,
  harvesting, or other automated collection.
- CBS reserves the right to change, discontinue, restrict, or terminate access.

**Implications encoded in this repo:**

1. The MVP is **local-first** and runs inside the **user's own authenticated CBS session**
   via the browser extension. There is no server-side credential harvesting and no
   standing scraper against CBS infrastructure.
2. CBS is treated as a source of **user-authorized league-specific state** (settings, live
   draft events) — not as a general data backbone. Bulk NFL/fantasy data comes from
   nflverse and licensed providers instead.
3. The **unofficial/deprecated CBS API adapter** ships **disabled**
   (`JAAFFL_ENABLE_CBS_UNOFFICIAL_API=false`) and is a best-effort fallback only, behind the
   provider interface so it can be turned off at runtime.
4. **Do not** build or ship a commercial product that depends on CBS scraping or on
   personal-use content rights.

## Data-provider licensing

| Provider           | Tier / cost                                  | Use posture in this repo                          |
| ------------------ | -------------------------------------------- | ------------------------------------------------- |
| nflverse/nflfastR  | Free / open                                  | Default historical + validation base              |
| FantasyPros API    | Free prototype; ~$5.99/mo personal Premium   | Personal, **non-commercial** only; off by default |
| SportsDataIO       | Commercial (trial available)                 | Commercial track only; off by default             |
| Sportradar         | Commercial                                   | Commercial track only; off by default             |

- The FantasyPros low-cost Premium tier is **personal, non-commercial**. A commercial
  launch must move to FantasyPros Commercial, SportsDataIO, Sportradar, or equivalent.
- All non-free providers default to **off** in `.env.example` and `jaaffl.config`. Enabling
  one is an explicit, license-aware decision.

## Two tracks

- **Personal research tool** — local-first; CBS browser sync + nflverse + FantasyPros
  Premium; no required paid cloud. This is what the scaffold targets.
- **Commercializable platform** — must swap in licensed real-time feeds and limit CBS to
  user-authorized league-state extraction. Designed for via the provider interface, but a
  legal review is a prerequisite, not an afterthought.

## Data-handling notes

- Persist league snapshots **locally** from first use so the tool owns its historical
  manager-tendency dataset rather than depending on CBS history staying accessible.
- Keep the extension's permissions **narrowly scoped** to CBS fantasy league/draft pages.
  Use the cookies API only if strictly necessary.
