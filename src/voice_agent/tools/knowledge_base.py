"""The retrieval tool the agent can call mid-conversation.

Note what is *not* here: anything about cars, or Spinny, or any one company. The
tool retrieves from whatever was ingested; the domain lives in the documents under
`knowledge/` and in the config's prompt. Point it at a different folder of PDFs
and the same code answers questions about something else.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from livekit.agents import RunContext, function_tool

from voice_agent.rag.store import KnowledgeBase, KnowledgeBaseError, Passage
from voice_agent.tools.registry import register_tool

logger = logging.getLogger("voice-agent.tools")

TOP_K = 3

# Measured against the sample knowledge base, top hit per question:
#   on-topic  ("how long is the warranty")   0.20 - 0.51
#   off-topic ("who won the world cup")      0.03 - 0.09
# 0.15 sits in that gap. Retrieval always returns *something*, so without a
# threshold the agent would confidently read out an unrelated policy — worse in a
# voice call than on a page, because the caller cannot skim and check.
MIN_SCORE = 0.15

_kb: KnowledgeBase | None = None


def _knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


def _format(passages: list[Passage]) -> str:
    """Render passages for the LLM — headed, plain, and short enough to speak."""
    return "\n\n".join(f"[{p.section}]\n{p.text}" for p in passages if p.text.strip())


@register_tool("knowledge_base")
@function_tool
async def knowledge_base(context: RunContext[Any], question: str) -> str:
    """Look up the company's official policies, terms and published information.

    Use this whenever the caller asks about company policy, guarantees, warranties,
    returns or refunds, inspections, pricing rules, paperwork, delivery, financing,
    support hours, or anything else that would be written down by the company.
    Prefer calling this over answering from memory: the documents are the source of
    truth and your own recollection may be out of date.

    Args:
        question: The caller's question, in their own words.
    """
    started = time.perf_counter()
    try:
        # The Pinecone SDK is synchronous. Calling it directly would block the
        # event loop that is also moving audio frames, which is heard as a stall
        # in the middle of the conversation.
        passages = await asyncio.to_thread(_knowledge_base().search, question, TOP_K)
    except KnowledgeBaseError as exc:
        logger.warning("knowledge base lookup failed: %s", exc)
        return (
            "The knowledge base is unavailable right now, so I could not check "
            "that. Tell the caller you will follow up rather than guessing."
        )

    elapsed_ms = (time.perf_counter() - started) * 1000
    relevant = [p for p in passages if p.score >= MIN_SCORE]

    logger.info(
        "knowledge_base(%r) -> %d/%d passages in %.0f ms (best score %.3f)",
        question,
        len(relevant),
        len(passages),
        elapsed_ms,
        passages[0].score if passages else 0.0,
    )

    if not relevant:
        return (
            "Nothing in the company documents covers that. Say you do not have "
            "that information rather than guessing."
        )
    return _format(relevant)
