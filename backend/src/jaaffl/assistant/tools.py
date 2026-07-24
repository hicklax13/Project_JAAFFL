"""Typed function tools exposed to the OpenAI Responses API.

The assistant is text-only. Function calling drives our own data store and league-specific
lookups; file search (uploaded rules/exports) and web search (breaking news) are optional
and config-gated. Actual dispatch to backend functions is wired in Stage 7.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jaaffl.assistant.explain import explain_pick
from jaaffl.config import EngineParams, get_settings
from jaaffl.domain import DraftState, LeagueSettings, Recommendation

FUNCTION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "query_warehouse",
        "description": "Run a read-only query against the local JAAFFL warehouse "
        "(players, stats, projections, draft snapshots).",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Natural-language data question."}
            },
            "required": ["question"],
        },
    },
    {
        "type": "function",
        "name": "league_summary",
        "description": "Summarize current league settings and live draft state.",
        "parameters": {
            "type": "object",
            "properties": {"league_id": {"type": "string"}},
            "required": ["league_id"],
        },
    },
    {
        "type": "function",
        "name": "explain_recommendation",
        "description": "Explain why the engine ranks a player where it does for the current pick.",
        "parameters": {
            "type": "object",
            "properties": {
                "league_id": {"type": "string"},
                "player_id": {"type": "string"},
            },
            "required": ["league_id", "player_id"],
        },
    },
    {
        "type": "function",
        "name": "player_news",
        "description": "Look up recent news/injury context for a player.",
        "parameters": {
            "type": "object",
            "properties": {"player_id": {"type": "string"}},
            "required": ["player_id"],
        },
    },
]


def build_tools() -> list[dict[str, Any]]:
    """Assemble the tool list for a Responses API call, honoring config flags."""
    tools: list[dict[str, Any]] = list(FUNCTION_TOOLS)
    if get_settings().jaaffl_assistant_enable_web_search:
        tools.append({"type": "web_search"})
    # TODO(stage 7): append {"type": "file_search", ...} when a vector store is configured.
    return tools


@dataclass
class AssistantContext:
    """Injected, network-free data access for tool dispatch.

    The OpenAI Responses API loop (owner ``OPENAI_API_KEY``) supplies this from ``app.state``; tests
    pass fakes. Only ``recommendation`` is required (explain_recommendation); ``league_settings`` +
    ``draft_state`` power league_summary; ``params`` (κ/α) sharpen the prose. Plain callables keep
    the tool layer decoupled from the API and the LLM runtime.
    """

    recommendation: Callable[[str], Recommendation | None]
    league_settings: Callable[[str], LeagueSettings | None] | None = None
    draft_state: Callable[[str], DraftState | None] | None = None
    params: EngineParams | None = None


def dispatch(name: str, arguments: dict[str, Any], *, context: AssistantContext) -> dict[str, Any]:
    """Execute a tool call by name and return a JSON-serializable result.

    The two deterministic tools run here with no OpenAI/network. ``query_warehouse`` (NL→data) and
    ``player_news`` (external feed) need the LLM runtime / a news source and stay unwired until the
    Responses API loop lands — surfaced as ``NotImplementedError``, never a silent empty result.
    """
    if name == "explain_recommendation":
        return _explain_recommendation(arguments, context)
    if name == "league_summary":
        return _league_summary(arguments, context)
    if name in ("query_warehouse", "player_news"):
        raise NotImplementedError(
            f"tool '{name}' needs the assistant runtime (LLM data interpretation / news feed), "
            "wired with the OpenAI Responses API (stage 7 — owner OPENAI_API_KEY)"
        )
    raise ValueError(f"unknown tool: {name}")


def _explain_recommendation(arguments: dict[str, Any], context: AssistantContext) -> dict[str, Any]:
    league_id, player_id = arguments["league_id"], arguments["player_id"]
    rec = context.recommendation(league_id)
    if rec is None:
        return {"error": "no recommendation available yet", "league_id": league_id}
    pick = next((p for p in rec.ranked if p.player_id == player_id), None)
    if pick is None:
        return {
            "error": "player is not in the current ranked pool",
            "league_id": league_id,
            "player_id": player_id,
        }
    return {
        "league_id": league_id,
        "player_id": player_id,
        "as_of_overall_pick": rec.as_of_overall_pick,
        "score": pick.score,
        "explanation": explain_pick(pick, context.params),
    }


def _league_summary(arguments: dict[str, Any], context: AssistantContext) -> dict[str, Any]:
    league_id = arguments["league_id"]
    settings = context.league_settings(league_id) if context.league_settings else None
    state = context.draft_state(league_id) if context.draft_state else None
    if settings is None and state is None:
        return {"error": "no league data available", "league_id": league_id}
    out: dict[str, Any] = {"league_id": league_id}
    if settings is not None:
        out["settings"] = {
            "team_count": settings.team_count,
            "draft_type": settings.draft_type,
            "roster": {slot.slot: slot.count for slot in settings.roster_slots},
        }
    if state is not None:
        out["draft"] = {
            "current_overall_pick": state.current_overall_pick,
            "on_the_clock_team_id": state.on_the_clock_team_id,
            "picks_made": len(state.picks),
            "complete": state.complete,
        }
    return out
