"""Extraction of (cbs_id, name, position, nfl_team) triples from real CBS record-mode captures
(docs/research/cbs-draft-protocol.md §5) for scripts/seed_cbs_crosswalk.py.

Deliberately uses a small INLINE HTML sample, not the git-ignored raw captures under
apps/extension/fixtures/cbs/ -- CI has no access to those (see the script's own module docstring
for the real-capture dry-run yield, verified separately, not in CI)."""

from __future__ import annotations

from jaaffl.data.cbs_extract import (
    CbsPlayer,
    canonical_cbs_position,
    extract_cbs_players,
    normalize_snippet_name,
)

# A small HTML sample exercising all three protocol §5 sources plus the edge cases: the "Last,
# First" snippet normalization (incl. a queue "*" star and a trailing "(POS TEAM)" annotation),
# the CBS->canonical position mapping (including the DEF->DST / PK->K aliases FFC also needs, and
# an unmappable code that must be dropped rather than guessed), source-2-over-source-3 name
# precedence for the same id, and a JS-template snippet (real dom-snapshots embed the CBS page's
# own row-rendering script verbatim) that must NOT be mistaken for a real rendered row.
_SAMPLE_HTML = """
<html><body>
<!-- source 1 (player-list row): name via an embedded source-3 snippet link, position+team via
     the row's <td align="left"> pair -->
<tr id="playerListDD_1111"
    data-rookie="0" style="height:17px;" class="bg2" align="right" valign="middle">
  <td align="left">
    <a href="/players/playerpage/snippet/1111" class="playerLink">Diggs, Stefon</a>
  </td>
  <td align="left">WR</td><td align="left">NE</td><td>6</td>
</tr>

<!-- source 1: raw CBS code "DEF" must map to canonical DST -->
<tr id="playerListDD_2222"
    data-rookie="0" style="height:17px;" class="bg2" align="right" valign="middle">
  <td align="left">
    <a href="/players/playerpage/snippet/2222" class="playerLink">49ers, San Francisco</a>
  </td>
  <td align="left">DEF</td><td align="left">SF</td><td>9</td>
</tr>

<!-- source 1: raw CBS code "PK" must map to canonical K -->
<tr id="playerListDD_3333"
    data-rookie="0" style="height:17px;" class="bg2" align="right" valign="middle">
  <td align="left">
    <a href="/players/playerpage/snippet/3333" class="playerLink">Tucker, Justin</a>
  </td>
  <td align="left">PK</td><td align="left">BAL</td><td>13</td>
</tr>

<!-- source 1: an unmappable position code -- must be dropped, never guessed -->
<tr id="playerListDD_4444"
    data-rookie="0" style="height:17px;" class="bg2" align="right" valign="middle">
  <td align="left">
    <a href="/players/playerpage/snippet/4444" class="playerLink">Somebody, A</a>
  </td>
  <td align="left">P</td><td align="left">XX</td><td>1</td>
</tr>

<!-- the CBS page's OWN row-rendering JS template, embedded verbatim in a real dom-snapshot.
     Uses a JS variable (+x+), never a literal digit id -- must not be mistaken for a real row. -->
<script>
u+="&lt;tr id='playerListDD_"+x+"' data-rookie='"+E.rookie+"'&gt;...";
</script>

<!-- source 2 (player page link): canonical "First Last", standalone id (no row) -->
<div class="playerInfo"><div class="player_name">
  <a href="/players/playerpage/5555/" target="_blank"><h1 class="name">Jahmyr Gibbs</h1></a>
</div></div>

<!-- source 3 (snippet link): queue "*" star + trailing "(POS TEAM)" annotation, standalone id --
     the parenthetical is NOT a position/team source (only source 1's row td pair is) -->
<tr><td align="left">
  <a href="/players/playerpage/snippet/6666" class="playerLink">*Achane, De'Von (RB MIA)</a>
</td></tr>

<!-- id seen by BOTH source 2 and source 3: source 2's "First Last" must win -->
<a href="/players/playerpage/7777/" target="_blank"><h1 class="name">Puka Nacua</h1></a>
<a href="/players/playerpage/snippet/7777" class="playerLink">Wrong Name, Should Not Win</a>
</body></html>
"""


# --- canonical_cbs_position ------------------------------------------------------------


def test_canonical_cbs_position_passes_through_known_codes() -> None:
    for code in ("QB", "RB", "WR", "TE", "K", "DST"):
        assert canonical_cbs_position(code) == code


def test_canonical_cbs_position_maps_def_and_pk_like_the_ffc_adapter() -> None:
    assert canonical_cbs_position("DEF") == "DST"
    assert canonical_cbs_position("PK") == "K"


def test_canonical_cbs_position_is_case_insensitive() -> None:
    assert canonical_cbs_position("wr") == "WR"
    assert canonical_cbs_position("def") == "DST"


def test_canonical_cbs_position_unknown_code_is_none() -> None:
    assert canonical_cbs_position("P") is None  # punter -- not a league position, never guessed


def test_canonical_cbs_position_blank_is_none() -> None:
    assert canonical_cbs_position(None) is None
    assert canonical_cbs_position("") is None


# --- normalize_snippet_name ("Last, First" -> "First Last") ----------------------------


def test_normalize_snippet_name_swaps_last_first() -> None:
    assert normalize_snippet_name("Gibbs, Jahmyr") == "Jahmyr Gibbs"


def test_normalize_snippet_name_strips_queue_star() -> None:
    assert normalize_snippet_name("*McCaffrey, Christian") == "Christian McCaffrey"


def test_normalize_snippet_name_strips_trailing_pos_team_annotation() -> None:
    assert normalize_snippet_name("*Achane, De'Von (RB MIA)") == "De'Von Achane"


def test_normalize_snippet_name_passes_through_names_without_a_comma() -> None:
    assert normalize_snippet_name("Jahmyr Gibbs") == "Jahmyr Gibbs"


# --- extract_cbs_players: end-to-end over the inline sample -----------------------------


def test_extract_finds_all_seeded_ids() -> None:
    players = extract_cbs_players([_SAMPLE_HTML])
    assert set(players) == {"1111", "2222", "3333", "4444", "5555", "6666", "7777"}


def test_extract_source1_row_gives_name_position_and_team() -> None:
    players = extract_cbs_players([_SAMPLE_HTML])
    assert players["1111"] == CbsPlayer(
        cbs_id="1111", name="Stefon Diggs", position="WR", nfl_team="NE"
    )


def test_extract_maps_def_position_code_to_dst() -> None:
    players = extract_cbs_players([_SAMPLE_HTML])
    assert players["2222"] == CbsPlayer(
        cbs_id="2222", name="San Francisco 49ers", position="DST", nfl_team="SF"
    )


def test_extract_maps_pk_position_code_to_k() -> None:
    players = extract_cbs_players([_SAMPLE_HTML])
    assert players["3333"] == CbsPlayer(
        cbs_id="3333", name="Justin Tucker", position="K", nfl_team="BAL"
    )


def test_extract_drops_unmappable_position_rather_than_guessing() -> None:
    players = extract_cbs_players([_SAMPLE_HTML])
    assert players["4444"].position is None
    assert players["4444"].nfl_team is None
    assert players["4444"].name == "A Somebody"  # name still extracted from the snippet link


def test_extract_js_template_row_never_yields_a_spurious_id() -> None:
    players = extract_cbs_players([_SAMPLE_HTML])
    assert "x" not in players  # the JS variable "x" was never captured as a literal id


def test_extract_source2_gives_canonical_first_last_with_no_position() -> None:
    players = extract_cbs_players([_SAMPLE_HTML])
    assert players["5555"] == CbsPlayer(
        cbs_id="5555", name="Jahmyr Gibbs", position=None, nfl_team=None
    )


def test_extract_source3_standalone_normalizes_and_has_no_position() -> None:
    players = extract_cbs_players([_SAMPLE_HTML])
    assert players["6666"] == CbsPlayer(
        cbs_id="6666", name="De'Von Achane", position=None, nfl_team=None
    )


def test_extract_source2_wins_over_source3_for_the_same_id() -> None:
    players = extract_cbs_players([_SAMPLE_HTML])
    assert players["7777"].name == "Puka Nacua"


# --- extract_cbs_players: accumulates fields for the same id ACROSS multiple texts ------


def test_extract_merges_name_and_position_seen_in_different_texts() -> None:
    """A real draft has many dom-snapshots/xhr bodies over time; the same player's name and
    position+team can land in DIFFERENT captured blobs. A per-text extract-then-merge would drop
    the row's position/team when that text lacked a name (and vice versa) -- this pins the fix:
    accumulation must happen ACROSS all texts before a name is required to emit a record."""
    text_with_row_only = (
        '<tr id="playerListDD_8888" data-rookie="0" class="bg2" align="right" valign="middle">'
        # real rows always nest the name in an <a>, which is what keeps this cell from being
        # mistaken for the position/team pair below (its content is not "[^<]*"-matchable whole).
        '<td align="left"><a href="/x">no name here</a></td>'
        '<td align="left">TE</td><td align="left">KC</td>'
        "</tr>"
    )
    text_with_name_only = (
        '<a href="/players/playerpage/8888/" target="_blank"><h1 class="name">Travis Kelce</h1></a>'
    )
    players = extract_cbs_players([text_with_row_only, text_with_name_only])
    assert players["8888"] == CbsPlayer(
        cbs_id="8888", name="Travis Kelce", position="TE", nfl_team="KC"
    )


def test_extract_row_only_id_with_no_name_anywhere_is_dropped() -> None:
    """A position+team row with no name in ANY scanned text is useless to resolve_or_link (name
    is required) -- dropped, not emitted with name=None."""
    text = (
        '<tr id="playerListDD_9999" data-rookie="0" class="bg2" align="right" valign="middle">'
        '<td align="left">nameless</td>'
        '<td align="left">RB</td><td align="left">DAL</td>'
        "</tr>"
    )
    players = extract_cbs_players([text])
    assert "9999" not in players


def test_extract_returns_empty_dict_for_no_matches() -> None:
    assert extract_cbs_players(["<html><body>nothing relevant here</body></html>"]) == {}
