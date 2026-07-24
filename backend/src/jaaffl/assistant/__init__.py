"""Text-only AI assistant (Stage 7). No voice/Realtime — see ADR 0003."""

from jaaffl.assistant.explain import explain_pick
from jaaffl.assistant.tools import FUNCTION_TOOLS, AssistantContext, build_tools, dispatch

__all__ = ["FUNCTION_TOOLS", "AssistantContext", "build_tools", "dispatch", "explain_pick"]
