"""Tools the agent can call, looked up by the names listed in a config.

Same shape as the provider registry: a name maps to a thing, and a config opts in
by name. Nothing use-case-specific is imported by the worker — a config with
`"tools": []` runs perfectly well, which is the point.

To add one::

    @register_tool("property_search")
    @function_tool
    async def property_search(ctx: RunContext, query: str) -> str:
        ...
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

TOOLS: dict[str, Any] = {}

F = TypeVar("F")


class UnknownToolError(ValueError):
    """A config listed a tool name that nothing has registered."""


def register_tool(name: str) -> Callable[[F], F]:
    def decorator(tool: F) -> F:
        TOOLS[name] = tool
        return tool

    return decorator


def resolve_tools(names: Sequence[str]) -> list[Any]:
    """Names -> tool objects, failing loudly and early on a typo."""
    missing = [name for name in names if name not in TOOLS]
    if missing:
        known = ", ".join(sorted(TOOLS)) or "none registered"
        raise UnknownToolError(
            f"unknown tool(s): {', '.join(missing)}; available: {known}"
        )
    return [TOOLS[name] for name in names]
