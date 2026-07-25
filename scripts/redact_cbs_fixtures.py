#!/usr/bin/env python
"""Redact + curate golden fixtures from the real CBS record-mode capture.

Reads the git-ignored raw captures under ``apps/extension/fixtures/cbs/*.jsonl`` (owner
record-mode session — see docs/research/cbs-draft-protocol.md) and writes a small,
representative, REDACTED set of committed golden fixtures under
``apps/extension/tests/fixtures/cbs/*.json``. Each output file is exactly one recorder
envelope (``{"kind", "ts", "payload": {"url", "body", "ts", "seq"}}``) — the same shape
``apps/extension/src/lib/record.ts`` writes — so a future ``parse.ts`` rewrite can replay
them as-is. Selection covers the real CBS frame vocabulary:

  - picks-completed.autopick.json   -- source:"autopick", newstate.upcomingorder populated
  - picks-completed.final.json      -- the draft-over sentinel (state:"completed",
                                        upcomingorder:"") -- source is "userpick" in the
                                        current capture, so this file doubles as the human
                                        (non-autopick) pick example too
  - picks-completed.human.json      -- ONLY written if the final frame above was itself an
                                        autopick (i.e. no human pick would otherwise be
                                        represented)
  - subscribe-response.json         -- the (one) subscribe/response frame; its ~61 KB
                                        player pool (fullstate.teams / fullstate.results)
                                        is truncated to a handful of entries -- structure
                                        kept, bulk dropped
  - auth-reply.json                 -- auth/reply handshake echo (owner id + display name)
  - keepalive.json                  -- ``{"type":"keepalive"}`` heartbeat
  - heartbeat.json                  -- the bare-numeric, NON-JSON heartbeat frame
  - pick-request.json               -- an outbound (ws-send) pick/request

Redaction (consistent across every emitted fixture -- the same raw value always maps to
the same replacement, so cross-references between files still line up):
  - ownerid-shaped values (bare ``ownerid`` fields, ``auth.id``, the sibling ``id`` next to
    an ``auth`` block, and each comma-separated token of ``ownerspresent``) -> owner-1,
    owner-2, ...
  - human/team display names (``attrib.name``) -> Team 1, Team 2, ...
  - email-shaped strings -> "[redacted-email]"
  - league/draft ids and CBS's own k8s hostnames are NOT personal data -> kept verbatim
  - NFL player names/positions/teams/CBS player ids are NEVER touched -- the real protocol
    is id-only for picks, so there is nothing player-identifying to redact in the first
    place (see docs/research/cbs-draft-protocol.md section 5)

The owner-id / display-name maps are built from a FULL-CORPUS scan (every raw file, every
frame) before any fixture is selected, so the mapping is stable no matter which specific
lines end up chosen -- and so a value that appears in one raw file maps the same way if it
also appears in another. After structural (key-path-aware) redaction, a defense-in-depth
pass string-replaces any leftover literal occurrence of a known sensitive value in the
serialized output, so a field the structural pass didn't anticipate still can't leak.

Usage (from the repo root; no backend/package dependency -- stdlib only)::

    .venv/Scripts/python.exe scripts/redact_cbs_fixtures.py
    .venv/Scripts/python.exe scripts/redact_cbs_fixtures.py --raw-dir path\\to\\other\\capture
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = REPO_ROOT / "apps" / "extension" / "fixtures" / "cbs"
DEFAULT_OUT_DIR = REPO_ROOT / "apps" / "extension" / "tests" / "fixtures" / "cbs"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")


# --------------------------------------------------------------------------------------- #
# Raw-capture iteration
# --------------------------------------------------------------------------------------- #


def iter_envelopes(raw_files: list[Path]) -> Iterator[tuple[Path, int, dict]]:
    """Yield (file, 1-based line number, parsed outer envelope) for every raw line that
    parses as JSON. Files are visited in sorted (== chronological, timestamp-named) order.
    Unparseable lines (e.g. the two known split-write-race lines) are silently skipped --
    the caller can diff line counts against `wc -l` if it needs to know how many."""
    for f in sorted(raw_files):
        with f.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield f, lineno, json.loads(line)
                except json.JSONDecodeError:
                    continue


def iter_ws_frames(
    raw_files: list[Path],
) -> Iterator[tuple[Path, int, dict, dict | None]]:
    """Yield (file, lineno, envelope, parsed_frame) for every ws-message/ws-send line.
    `parsed_frame` is None for non-JSON bodies (bare-numeric heartbeats) -- NUL-strip first,
    per docs/research/cbs-draft-protocol.md section 1, or json.loads throws "Extra data"."""
    for f, lineno, envelope in iter_envelopes(raw_files):
        if envelope.get("kind") not in ("ws-message", "ws-send"):
            continue
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            continue
        body = payload.get("body", "")
        if not isinstance(body, str):
            continue
        stripped = body.rstrip("\x00").strip()
        if not stripped.startswith("{"):
            yield f, lineno, envelope, None
            continue
        try:
            frame = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        yield f, lineno, envelope, frame


def frame_kind(frame: dict) -> tuple[str, str]:
    """(type, subtype-or-event) -- CBS uses "subtype" for most frames, "event" for auth."""
    return str(frame.get("type", "?")), str(frame.get("subtype", frame.get("event", "?")))


# --------------------------------------------------------------------------------------- #
# Redaction maps -- built from the WHOLE corpus so mappings are stable across fixtures
# --------------------------------------------------------------------------------------- #


def build_redaction_maps(raw_files: list[Path]) -> tuple[dict[str, str], dict[str, str]]:
    """Scan every ws-message/ws-send frame in every raw file and collect every distinct
    ownerid-shaped value and every distinct display name, assigning deterministic
    owner-N / "Team N" labels in first-seen (== chronological) order."""
    owner_map: dict[str, str] = {}
    name_map: dict[str, str] = {}

    def see_owner(value: str) -> None:
        if value and value not in owner_map:
            owner_map[value] = f"owner-{len(owner_map) + 1}"

    def see_name(value: str) -> None:
        if value and value not in name_map:
            name_map[value] = f"Team {len(name_map) + 1}"

    def scan(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("ownerid"), str):
                see_owner(node["ownerid"])
            if isinstance(node.get("ownerspresent"), str):
                for tok in node["ownerspresent"].split(","):
                    tok = tok.strip()
                    if tok:
                        see_owner(tok)
            auth = node.get("auth")
            if isinstance(auth, dict) and isinstance(auth.get("id"), str):
                see_owner(auth["id"])
            attrib = node.get("attrib")
            if isinstance(attrib, dict) and isinstance(attrib.get("name"), str):
                see_name(attrib["name"])
            for value in node.values():
                scan(value)
        elif isinstance(node, list):
            for item in node:
                scan(item)

    for _f, _lineno, _envelope, frame in iter_ws_frames(raw_files):
        if frame is not None:
            scan(frame.get("payload"))

    return owner_map, name_map


# --------------------------------------------------------------------------------------- #
# Structural redaction -- scoped narrowly so NFL player data is never touched
# --------------------------------------------------------------------------------------- #


def redact(node: Any, owner_map: dict[str, str], name_map: dict[str, str]) -> Any:
    """Recursively redact one parsed CBS frame. Only touches the specific key shapes the
    real capture uses for owner/human identity -- a bare "ownerid" field, "ownerspresent"
    (comma-joined ownerid tokens), and the auth-record shape
    {"auth": {"id": <ownerid>}, "id": <ownerid>, "attrib": {"name": <display name>}} seen in
    auth/reply's roster[]/user. Player ids/positions/team-ids never match these shapes."""
    if isinstance(node, dict):
        if isinstance(node.get("ownerid"), str):
            node["ownerid"] = owner_map.get(node["ownerid"], node["ownerid"])
        if isinstance(node.get("ownerspresent"), str) and node["ownerspresent"]:
            node["ownerspresent"] = ",".join(
                owner_map.get(tok, tok) for tok in node["ownerspresent"].split(",")
            )
        auth = node.get("auth")
        if isinstance(auth, dict) and isinstance(auth.get("id"), str):
            auth["id"] = owner_map.get(auth["id"], auth["id"])
        # sibling "id" on an auth-record shares the same value as auth.id -- only redact
        # when it is ALREADY a known owner token, so player/team ids are never touched.
        if isinstance(node.get("id"), str) and node["id"] in owner_map:
            node["id"] = owner_map[node["id"]]
        attrib = node.get("attrib")
        if isinstance(attrib, dict) and isinstance(attrib.get("name"), str):
            attrib["name"] = name_map.get(attrib["name"], attrib["name"])
        for key, value in list(node.items()):
            node[key] = redact(value, owner_map, name_map)
        return node
    if isinstance(node, list):
        return [redact(item, owner_map, name_map) for item in node]
    return node


def safety_net(text: str, owner_map: dict[str, str], name_map: dict[str, str]) -> str:
    """Defense-in-depth: string-replace any leftover literal occurrence of a known
    sensitive value in the SERIALIZED fixture text, longest-first (avoids partial-token
    collisions), then scrub anything email-shaped. Should be a no-op after `redact()` --
    kept as a net for whatever the structural pass didn't anticipate."""
    for raw, replacement in sorted(owner_map.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(raw, replacement)
    for raw, replacement in sorted(name_map.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(raw, replacement)
    return EMAIL_RE.sub("[redacted-email]", text)


def truncate_fullstate(frame: dict, max_teams: int, max_players: int, max_results: int) -> None:
    """Drop the ~61 KB bulk of a subscribe/response's fullstate player pool down to a
    handful of entries while keeping the map-of-maps STRUCTURE intact (plan: keep team "1"
    -- the connecting client's own team -- plus one more; each team's `players` map and the
    flat `results` map are both truncated the same way). Per-team roster summary counts
    (filled/draft_vacancies) are left as the REAL captured values, not resynthesized to
    match the truncated count -- they are not personal data and rewriting them would make
    the fixture lie about what was actually observed."""
    fullstate = frame.get("payload", {}).get("fullstate")
    if not isinstance(fullstate, dict):
        return
    teams = fullstate.get("teams")
    if isinstance(teams, dict) and teams:
        keep_ids = sorted(teams.keys(), key=lambda k: int(k))[:max_teams]
        fullstate["teams"] = {tid: teams[tid] for tid in keep_ids}
        for team in fullstate["teams"].values():
            players = team.get("players")
            if isinstance(players, dict) and len(players) > max_players:
                team["players"] = dict(list(players.items())[:max_players])
    results = fullstate.get("results")
    if isinstance(results, dict) and len(results) > max_results:
        keep_keys = sorted(results.keys(), key=lambda k: int(k))[:max_results]
        fullstate["results"] = {k: results[k] for k in keep_keys}


# --------------------------------------------------------------------------------------- #
# Fixture selection -- rule-based (not hardcoded line numbers) so a future re-capture
# regenerates sensibly.
# --------------------------------------------------------------------------------------- #

Selected = dict[str, tuple[Path, int, dict, bool]]  # name -> (file, lineno, envelope, truncate)


def select_fixtures(raw_files: list[Path]) -> Selected:
    selected: Selected = {}
    picks_final: tuple[Path, int, dict, dict] | None = None
    picks_autopick: tuple[Path, int, dict, dict] | None = None
    picks_human: tuple[Path, int, dict, dict] | None = None

    for f, lineno, envelope, frame in iter_ws_frames(raw_files):
        if frame is None:
            if "heartbeat.json" not in selected:
                selected["heartbeat.json"] = (f, lineno, envelope, False)
            continue

        ftype, fsub = frame_kind(frame)
        payload = frame.get("payload", {})

        if ftype == "picks" and fsub == "completed" and envelope["kind"] == "ws-message":
            picks = payload.get("picks") or [{}]
            source = picks[0].get("source")
            newstate = payload.get("newstate", {})
            if picks_autopick is None and source == "autopick" and newstate.get("upcomingorder"):
                picks_autopick = (f, lineno, envelope, frame)
            if picks_final is None and newstate.get("state") == "completed":
                picks_final = (f, lineno, envelope, frame)
            if picks_human is None and source is not None and source != "autopick":
                picks_human = (f, lineno, envelope, frame)

        elif (
            ftype == "subscribe"
            and fsub == "response"
            and "subscribe-response.json" not in selected
        ):
            selected["subscribe-response.json"] = (f, lineno, envelope, True)

        elif ftype == "auth" and fsub == "reply" and "auth-reply.json" not in selected:
            selected["auth-reply.json"] = (f, lineno, envelope, False)

        elif ftype == "keepalive" and "keepalive.json" not in selected:
            selected["keepalive.json"] = (f, lineno, envelope, False)

        elif (
            ftype == "pick"
            and fsub == "request"
            and envelope["kind"] == "ws-send"
            and "pick-request.json" not in selected
        ):
            selected["pick-request.json"] = (f, lineno, envelope, False)

    if picks_autopick:
        f, lineno, envelope, _frame = picks_autopick
        selected["picks-completed.autopick.json"] = (f, lineno, envelope, False)
    if picks_final:
        f, lineno, envelope, frame = picks_final
        selected["picks-completed.final.json"] = (f, lineno, envelope, False)
        final_source = (frame.get("payload", {}).get("picks") or [{}])[0].get("source")
        if final_source == "autopick" and picks_human:
            f, lineno, envelope, _frame = picks_human
            selected["picks-completed.human.json"] = (f, lineno, envelope, False)

    return selected


# --------------------------------------------------------------------------------------- #
# Build + write
# --------------------------------------------------------------------------------------- #


def build_fixture(
    envelope: dict,
    owner_map: dict[str, str],
    name_map: dict[str, str],
    truncate: bool,
    max_teams: int,
    max_players: int,
    max_results: int,
) -> dict:
    """Return a NEW envelope dict with payload.body redacted (and, for the subscribe
    response, truncated). The original trailing NUL is preserved iff the raw frame had
    one -- some real frames do, some don't; we reproduce what was actually observed rather
    than fabricating or stripping framing."""
    payload = envelope["payload"]
    body = payload["body"]
    had_nul = body.endswith("\x00")
    stripped = body.rstrip("\x00").strip()

    if stripped.startswith("{"):
        frame = json.loads(stripped)
        frame = redact(frame, owner_map, name_map)
        if truncate:
            truncate_fullstate(frame, max_teams, max_players, max_results)
        new_body = json.dumps(frame, separators=(",", ":"), ensure_ascii=False)
    else:
        new_body = stripped  # bare-numeric heartbeat -- nothing to parse or redact

    new_body = safety_net(new_body, owner_map, name_map)
    if had_nul:
        new_body += "\x00"

    new_envelope = dict(envelope)
    new_payload = dict(payload)
    new_payload["body"] = new_body
    new_envelope["payload"] = new_payload
    return new_envelope


def verify_fixture(path: Path, owner_map: dict[str, str], name_map: dict[str, str]) -> list[str]:
    """Round-trip + leak check on ONE already-written fixture. Returns a list of problems
    (empty == clean)."""
    problems = []
    text = path.read_text(encoding="utf-8")
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"{path.name}: outer envelope is not valid JSON: {exc}"]
    body = envelope.get("payload", {}).get("body", "")
    stripped = body.rstrip("\x00").strip()
    if stripped.startswith("{"):
        try:
            json.loads(stripped)
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}: payload.body does not round-trip after NUL-strip: {exc}")
    for raw in list(owner_map) + list(name_map):
        if raw and raw in text:
            problems.append(f"{path.name}: leftover literal sensitive value {raw!r}")
    if EMAIL_RE.search(re.sub(r"\[redacted-email]", "", text)):
        problems.append(f"{path.name}: leftover email-shaped string")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--max-teams", type=int, default=2, help="subscribe-response: teams to keep"
    )
    parser.add_argument("--max-players-per-team", type=int, default=2)
    parser.add_argument("--max-results", type=int, default=4)
    args = parser.parse_args(argv)

    if not args.raw_dir.is_dir():
        print(f"[redact] raw capture dir not found: {args.raw_dir}", file=sys.stderr)
        print(
            "[redact] (expected on a machine without the git-ignored raw session)", file=sys.stderr
        )
        return 1
    raw_files = sorted(args.raw_dir.glob("*.jsonl"))
    if not raw_files:
        print(f"[redact] no *.jsonl captures in {args.raw_dir}", file=sys.stderr)
        return 1

    print(
        f"[redact] scanning {len(raw_files)} raw capture file(s) for redaction targets ...",
        file=sys.stderr,
    )
    owner_map, name_map = build_redaction_maps(raw_files)
    print(
        f"[redact] {len(owner_map)} distinct ownerid-shaped value(s) -> owner-N, "
        f"{len(name_map)} distinct display name(s) -> Team N",
        file=sys.stderr,
    )

    selected = select_fixtures(raw_files)
    if not selected:
        print(
            "[redact] no fixture-worthy frames found -- capture shape may have changed",
            file=sys.stderr,
        )
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stale = [p for p in args.out_dir.glob("*.json") if p.name not in selected]
    for p in stale:
        print(f"[redact] removing stale fixture from a prior run: {p.name}", file=sys.stderr)
        p.unlink()

    written: list[Path] = []
    for name, (src_file, src_line, envelope, truncate) in sorted(selected.items()):
        fixture = build_fixture(
            envelope,
            owner_map,
            name_map,
            truncate,
            args.max_teams,
            args.max_players_per_team,
            args.max_results,
        )
        out_path = args.out_dir / name
        with out_path.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(fixture, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        written.append(out_path)
        size = out_path.stat().st_size
        print(f"[redact] wrote {name:<34} <- {src_file.name}:{src_line}  ({size} bytes)")

    problems: list[str] = []
    for path in written:
        problems.extend(verify_fixture(path, owner_map, name_map))
    if problems:
        print("[redact] SELF-VERIFY FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    total_bytes = sum(p.stat().st_size for p in written)
    print(f"[redact] self-verify OK: {len(written)} fixture(s), {total_bytes} bytes total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
