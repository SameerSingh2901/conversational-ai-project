"""The one place free text passes through on its way into a stored call record.

Today it returns text unchanged. The value is that there is exactly one function
to change when redaction is needed, rather than a recorder, a store and an API
serialiser to hunt through.

It matters for this product specifically: callers say phone numbers, registration
numbers and addresses out loud. The moment transcripts are persisted, that file
holds personal data — which brings retention limits and a deletion path with it.
Routing text through one function from the start is close to free; retrofitting it
across a codebase is not.

Nothing calls this yet. This increment stores overview figures and the config
snapshot, neither of which is caller data. It activates when transcripts and tool
payloads land in the next increment.
"""

from __future__ import annotations

from collections.abc import Callable

Redactor = Callable[[str], str]


def identity(text: str) -> str:
    """Store text as spoken. The default while everything runs on a laptop."""
    return text


_redactor: Redactor = identity


def set_redactor(redactor: Redactor) -> None:
    """Swap the strategy — regex for obvious formats, a model for entities, or a
    hash so a caller can still be matched across calls without keeping the number.
    """
    global _redactor
    _redactor = redactor


def redact(text: str) -> str:
    return _redactor(text)
