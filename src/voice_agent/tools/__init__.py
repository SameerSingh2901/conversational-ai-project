"""LLM function tools exposed to the agent, registered by name.

Importing a tool module is what registers it, so every built-in tool has to be
imported here — otherwise a config naming it would fail with "unknown tool".
"""

# Imported for its registration side effect, not for the name.
from voice_agent.tools import knowledge_base as _knowledge_base  # noqa: F401
from voice_agent.tools.registry import (
    TOOLS,
    UnknownToolError,
    register_tool,
    resolve_tools,
)

__all__ = ["TOOLS", "UnknownToolError", "register_tool", "resolve_tools"]
