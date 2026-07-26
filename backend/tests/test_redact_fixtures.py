"""Regression cover for ``scripts/redact_cbs_fixtures.py`` — the PII gate on committed fixtures.

The script had none, and it is the one place where the owner's real capture (their email, their
ownerid, other real drafters' ids and team names) is turned into something committable. Two
properties matter and pull in opposite directions:

1. **It must not leak.** Every known sensitive value has to be gone from the output.
2. **It must not lie.** The output has to remain the frame CBS actually sent, so a parser test
   run against it is evidence about the real protocol.

Property 2 is the one that broke. ``safety_net`` replaced each sensitive literal as a bare
SUBSTRING of the serialized fixture, which is safe only while every sensitive value happens to be
long and unusual. The owner's 2026-07-25 capture contains a real one-character team display name
(reproduced here as "x", not the observed character), and regenerating turned ``"upcomingorder"`` into ``"upcominTeam 5order"`` and ``"state":"picking"``
into ``"state":"pickinTeam 5"`` — corrupting the two fields the parser reads to detect the draft
order and completion, in a file whose whole purpose is to be ground truth.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script() -> ModuleType:
    """Import the standalone (stdlib-only) redaction script by path."""
    path = REPO_ROOT / "scripts" / "redact_cbs_fixtures.py"
    spec = importlib.util.spec_from_file_location("redact_cbs_fixtures", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


redact_script = _load_script()


def _envelope(frame: dict) -> dict:
    """A recorder envelope whose body is the NUL-terminated frame, as record.ts writes it."""
    return {
        "kind": "ws-message",
        "ts": 1784942162000,
        "payload": {
            "url": "wss://k8s-draft.prod.fantasy.cbssports.cloud:443/",
            "seq": 1,
            "ts": "2026-07-25T01:16:02.000Z",
            "body": json.dumps(frame, separators=(",", ":")) + "\x00",
        },
    }


def _build(frame: dict, owner_map: dict[str, str], name_map: dict[str, str]) -> dict:
    return redact_script.build_fixture(_envelope(frame), owner_map, name_map, False, 2, 2, 4)


def _body(fixture: dict) -> dict:
    return json.loads(fixture["payload"]["body"].rstrip("\x00"))


# A real CBS picks/completed frame, trimmed to the fields the parser reads. "upcomingorder" and
# "upcomingorder"/"picking" both contain the test's one-character name, mirroring the
# real capture's collision without reproducing the character a real drafter chose.
def _pick_frame(team_name: str) -> dict:
    return {
        "type": "picks",
        "subtype": "completed",
        "payload": {
            "newstate": {
                "opick": "2",
                "round": 1,
                "rounds": 14,
                "state": "picking",
                "onclockteamid": "2",
                "ondeckteamid": "3",
                "upcomingorder": "2,3,4,5,6,7,8,9,10,11,12",
                "ownerspresent": "ownertoken-aaa,ownertoken-bbb",
            },
            "picks": [{"playerid": "3162723", "teamid": "1", "source": "autopick"}],
            "fullstatedelta": {
                "order": "1,2,3,4,5,6,7,8,9,10,11,12",
                "teams": {"1": {"attrib": {"name": team_name}}},
            },
        },
    }


class TestShortDisplayNameDoesNotCorruptTheFrame:
    """A one-character team name must not rewrite the protocol's own vocabulary."""

    NAME_MAP = {"x": "Team 5"}
    OWNER_MAP = {"ownertoken-aaa": "owner-1", "ownertoken-bbb": "owner-2"}

    def test_protocol_key_names_survive(self) -> None:
        fixture = _build(_pick_frame("x"), self.OWNER_MAP, self.NAME_MAP)
        newstate = _body(fixture)["payload"]["newstate"]
        # The bug rendered this key as "upcominTeam 5order", so it vanished from the frame.
        assert "upcomingorder" in newstate
        assert newstate["upcomingorder"] == "2,3,4,5,6,7,8,9,10,11,12"

    def test_protocol_state_values_survive(self) -> None:
        fixture = _build(_pick_frame("x"), self.OWNER_MAP, self.NAME_MAP)
        # parse.ts keys draft_complete off state == "completed"; corrupting "picking" here
        # means the same substitution would corrupt "completed" in the terminal frame.
        assert _body(fixture)["payload"]["newstate"]["state"] == "picking"

    def test_the_draft_order_survives(self) -> None:
        fixture = _build(_pick_frame("x"), self.OWNER_MAP, self.NAME_MAP)
        order = _body(fixture)["payload"]["fullstatedelta"]["order"]
        assert order.split(",") == [str(i) for i in range(1, 13)]

    def test_the_short_name_is_still_redacted_where_it_really_appears(self) -> None:
        fixture = _build(_pick_frame("x"), self.OWNER_MAP, self.NAME_MAP)
        teams = _body(fixture)["payload"]["fullstatedelta"]["teams"]
        assert teams["1"]["attrib"]["name"] == "Team 5"

    def test_verify_does_not_report_a_phantom_leak(self, tmp_path: Path) -> None:
        # The same substring rule made verification report every fixture as leaking the character.
        out = tmp_path / "picks.json"
        out.write_text(
            json.dumps(_build(_pick_frame("x"), self.OWNER_MAP, self.NAME_MAP)), encoding="utf-8"
        )
        assert redact_script.verify_fixture(out, self.OWNER_MAP, self.NAME_MAP) == []


class TestTheNetStillCatchesWhatTheStructuralPassMisses:
    """Whole-value scrubbing must remain a real net, not a no-op."""

    def test_a_display_name_in_an_unanticipated_position_is_scrubbed(self) -> None:
        frame = _pick_frame("Longer Team Name")
        # Not a shape redact() knows about: a bare list of names under a novel key.
        frame["payload"]["chatters"] = ["Longer Team Name"]
        fixture = _build(frame, {}, {"Longer Team Name": "Team 5"})
        assert _body(fixture)["payload"]["chatters"] == ["Team 5"]

    def test_an_ownerid_embedded_in_a_compound_string_is_scrubbed(self) -> None:
        frame = _pick_frame("Longer Team Name")
        frame["payload"]["note"] = "session for ownertoken-aaa started"
        fixture = _build(frame, {"ownertoken-aaa": "owner-1"}, {})
        assert "ownertoken-aaa" not in json.dumps(fixture)

    def test_an_email_anywhere_is_scrubbed(self) -> None:
        frame = _pick_frame("Longer Team Name")
        frame["payload"]["note"] = "contact someone@example.com for details"
        fixture = _build(frame, {}, {})
        assert "someone@example.com" not in json.dumps(fixture)
        assert "[redacted-email]" in fixture["payload"]["body"]

    def test_a_comma_joined_token_is_scrubbed(self) -> None:
        frame = _pick_frame("Longer Team Name")
        frame["payload"]["newstate"]["ownerspresent"] = "ownertoken-aaa,ownertoken-bbb"
        fixture = _build(frame, {"ownertoken-aaa": "owner-1", "ownertoken-bbb": "owner-2"}, {})
        assert _body(fixture)["payload"]["newstate"]["ownerspresent"] == "owner-1,owner-2"


class TestTheLeakGuardActuallyFires:
    """A leak detector that never reports anything is worse than none — it turns "self-verify
    OK" into a claim about nothing. These pin that it still catches real leaks after the
    matching rules were narrowed."""

    def test_an_unredacted_long_token_is_reported(self, tmp_path: Path) -> None:
        out = tmp_path / "leaky.json"
        out.write_text(json.dumps(_envelope(_pick_frame("Team"))), encoding="utf-8")
        problems = redact_script.verify_fixture(out, {"ownertoken-aaa": "owner-1"}, {})
        assert any("ownertoken-aaa" in p for p in problems)

    def test_an_unredacted_short_name_as_a_whole_value_is_reported(self) -> None:
        # A one-char name as a complete JSON string value IS a leak, even though the same
        # letter inside "upcomingorder" is not. Both directions must hold.
        assert redact_script.leaked_values('{"name":"x"}', {}, {"x": "Team 5"}) == ["x"]
        assert redact_script.leaked_values('{"upcomingorder":"1,2"}', {}, {"x": "Team 5"}) == []

    def test_an_unredacted_email_is_reported(self, tmp_path: Path) -> None:
        out = tmp_path / "leaky.json"
        frame = _pick_frame("Team")
        frame["payload"]["note"] = "someone@example.com"
        out.write_text(json.dumps(_envelope(frame)), encoding="utf-8")
        problems = redact_script.verify_fixture(out, {}, {})
        assert any("email-shaped" in p for p in problems)


class TestTheNulTerminatorIsPreserved:
    """The terminator is the single most load-bearing byte in the protocol — a fixture that
    lost it would make every parser test pass against data the real socket never sends."""

    def test_the_body_still_ends_in_nul(self) -> None:
        fixture = _build(_pick_frame("Longer Team Name"), {}, {})
        assert fixture["payload"]["body"].endswith("\x00")
        assert json.loads(fixture["payload"]["body"].rstrip("\x00"))
