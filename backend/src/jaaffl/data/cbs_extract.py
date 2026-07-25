"""Extract ``(cbs_id, name, position, nfl_team)`` triples from real CBS record-mode captures for
crosswalk seeding (``scripts/seed_cbs_crosswalk.py``).

CBS's live draft-room ``picks/completed`` frames are ID-only (docs/research/cbs-draft-protocol.md
§3): no name, position, or NFL team rides along with a pick. The id -> identity mapping instead
has to be mined from the SAME record-mode capture's page content, which carries three independent
sources, in descending reliability (protocol doc §5):

1. **Player-list rows** -- ``<tr id="playerListDD_<cbsid>" ...> ... <td align="left">POS</td>
   <td align="left">TEAM</td>`` -- the only source of position + team; scoped to one row so a
   global scan can never attribute one player's position to another's.
2. **Player page links** -- ``/players/playerpage/<cbsid>/...<h1 class="name">First Last</h1>``
   -- the canonical "First Last" name.
3. **Snippet links** -- ``/players/playerpage/snippet/<cbsid>" class="playerLink">Last, First</a>``
   -- a lower-reliability name in "Last, First" form (queue widgets sometimes also append a
   " (POS TEAM)" annotation to the link text, which is stripped, not used -- source 1 alone owns
   position/team).

All three are plain regex scans over already-JSON/NUL-decoded text (a dom-snapshot's ``html``, or
a ``fetch``/``xhr`` response ``body`` -- see the script for how raw ``*.jsonl`` captures decode
into these strings). The regexes require literal digits immediately after ``playerListDD_`` /
``/playerpage/`` / ``/playerpage/snippet/``, which is what naturally excludes CBS's own row-
rendering JS *template* source (also embedded verbatim in a dom-snapshot, e.g.
``"<tr id='playerListDD_"+x+"'"``) -- ``x`` is a JS variable, never a literal id, so it never
matches ``\\d+``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# CBS's own draft-room HTML observed to already emit canonical QB/RB/WR/TE/K/DST directly (see
# the protocol doc §5 yield: 203/241 ids got a clean position from these exact codes). DEF/PK are
# mapped defensively for parity with the FFC adapter's DEF->DST / PK->K
# (jaaffl.providers.ffc._FFC_POSITION_MAP) in case a different CBS surface ever emits them too.
# Anything else maps to None (skipped) -- never guessed.
_CBS_POSITION_MAP = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "K": "K",
    "PK": "K",
    "DST": "DST",
    "DEF": "DST",
}


def canonical_cbs_position(raw: str | None) -> str | None:
    """Map a raw CBS position code to a canonical :class:`jaaffl.domain.Position` value, or
    ``None`` when the code is blank or unrecognized (never guessed)."""
    if not raw:
        return None
    return _CBS_POSITION_MAP.get(raw.strip().upper())


# --- source regexes ----------------------------------------------------------------------------
# Both quote styles are accepted defensively; only the real (double-quoted) form has been observed
# in a live capture -- CBS's row-rendering JS *template* source uses single quotes around a JS
# variable expression, which the required \d+ already excludes regardless of quote style.
_ROW_START_RE = re.compile(r'<tr\s+id=["\']playerListDD_(\d+)["\']')
_TD_LEFT_ALIGN_CELL = r'<td[^>]*align=(?:"left"|\'left\')[^>]*>([^<]*)</td>'
_TD_PAIR_RE = re.compile(_TD_LEFT_ALIGN_CELL + r"\s*" + _TD_LEFT_ALIGN_CELL)
_PLAYERPAGE_H1_RE = re.compile(
    r'/players/playerpage/(\d+)/[^"\'>]*["\'][^>]*>\s*<h1[^>]*class=["\']name["\'][^>]*>([^<]+)</h1>'
)
_SNIPPET_LINK_RE = re.compile(
    r'/players/playerpage/snippet/(\d+)["\']\s*class=["\']playerLink["\']>([^<]+)</a>'
)
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")  # a queue widget's trailing " (POS TEAM)"


def normalize_snippet_name(raw: str) -> str:
    """Normalize a source-3 snippet-link name: strip a queue '*' star and any trailing
    "(POS TEAM)" annotation, then swap CBS's "Last, First" into "First Last". A name with no
    comma (already "First Last", or a DST's plain nickname) passes through unchanged."""
    text = raw.strip().lstrip("*").strip()
    text = _TRAILING_PAREN_RE.sub("", text).strip()
    if "," in text:
        last, first = text.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return text


@dataclass(frozen=True)
class CbsPlayer:
    """One extracted CBS player identity, ready for ``Crosswalk.resolve_or_link("cbs", ...)``.
    ``position`` is already canonical (mapped via :func:`canonical_cbs_position`) or ``None`` when
    no player-list row was found for this id (or its code was unmappable) -- ``resolve_or_link``
    requires a canonical position, so callers must skip a ``None`` rather than guess one."""

    cbs_id: str
    name: str
    position: str | None = None
    nfl_team: str | None = None


def extract_cbs_players(texts: Iterable[str]) -> dict[str, CbsPlayer]:
    """Scan every capture text blob (dom-snapshot HTML / fetch|xhr body) for all three protocol
    §5 sources and return ``cbs_id -> CbsPlayer``.

    Accumulates GLOBALLY across every text in ``texts`` before assembling a record per id --
    deliberately NOT a per-text extract-then-merge, because the same player's name and
    position+team routinely land in DIFFERENT captured blobs over the course of a draft (a player
    once drafted drops out of later "available players" rows, but a news snippet or queue entry
    can still name them). Merging per-text would silently drop a row's position/team on any text
    that happened to lack a name for that same id.

    An id with a position/team row but NO name in any scanned text is dropped (never emitted with
    ``name=None``) -- :meth:`Crosswalk.resolve_or_link` requires a name, so such a record could
    never be seeded anyway.
    """
    # cbs_id -> best name so far; name_rank breaks ties by source reliability (2 > 1 -- source-2's
    # canonical "First Last" beats source-3's lower-reliability "Last, First").
    names: dict[str, str] = {}
    name_rank: dict[str, int] = {}
    pos_team: dict[str, tuple[str, str | None]] = {}

    for text in texts:
        for m in _PLAYERPAGE_H1_RE.finditer(text):
            cbs_id, name = m.group(1), m.group(2).strip()
            if name and name_rank.get(cbs_id, 0) < 2:
                names[cbs_id] = name
                name_rank[cbs_id] = 2

        for m in _SNIPPET_LINK_RE.finditer(text):
            cbs_id, raw_name = m.group(1), m.group(2)
            if name_rank.get(cbs_id, 0) < 1:
                normalized = normalize_snippet_name(raw_name)
                if normalized:
                    names[cbs_id] = normalized
                    name_rank[cbs_id] = 1

        for m in _ROW_START_RE.finditer(text):
            cbs_id = m.group(1)
            if cbs_id in pos_team:
                continue  # first row seen for this id wins (mirrors the name-rank tie policy)
            row_html = _row_slice(text, m.end())
            # Try every candidate td-pair in the row (not just the first): the name cell nests its
            # link so it never matches whole, but be defensive about markup variants that might
            # insert another plain-text cell before the real position/team pair.
            for pair in _TD_PAIR_RE.finditer(row_html):
                position = canonical_cbs_position(pair.group(1))
                if position is None:
                    continue  # unmappable/unknown code here -- keep looking, never guess
                team = pair.group(2).strip().upper() or None
                pos_team[cbs_id] = (position, team)
                break

    return {
        cbs_id: CbsPlayer(
            cbs_id=cbs_id,
            name=name,
            position=pos_team[cbs_id][0] if cbs_id in pos_team else None,
            nfl_team=pos_team[cbs_id][1] if cbs_id in pos_team else None,
        )
        for cbs_id, name in names.items()
    }


def _row_slice(text: str, row_start: int) -> str:
    """The text between a matched ``<tr id="playerListDD_...">`` and its own closing ``</tr>``
    (or the next ``<tr``, whichever comes first) -- bounds the position/team td-pair search to
    THIS row so it can never bleed into an adjacent player's cells."""
    end_tr = text.find("</tr>", row_start)
    next_tr = text.find("<tr", row_start)
    candidates = [i for i in (end_tr, next_tr) if i != -1]
    row_end = min(candidates) if candidates else len(text)
    return text[row_start:row_end]
