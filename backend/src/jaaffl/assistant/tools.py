"""Typed function tools exposed to the OpenAI Responses API.

The assistant is text-only. Function calling drives our own data store and league-specific
lookups; file search (uploaded rules/exports) and web search (breaking news) are optional
and config-gated. Actual dispatch to backend functions is wired in Stage 7.
"""

from __future__ import annotations

from typing import Any

from jaaffl.config import get_settings

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


def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool call by name and return a JSON-serializable result."""
    raise NotImplementedError("stage 7: wire tools to warehouse/engine/news lookups")
