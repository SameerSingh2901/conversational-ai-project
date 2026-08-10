"""Validation error types.

The shape here deliberately mirrors pydantic's: a list of errors, each carrying a
`loc` tuple pointing at the offending field. Keeping that shape means swapping in
pydantic later changes how errors are *produced*, not how callers consume them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldError:
    """A single problem, located at a path inside the config document."""

    loc: tuple[str, ...]
    msg: str

    def __str__(self) -> str:
        where = ".".join(self.loc) if self.loc else "<root>"
        return f"{where}: {self.msg}"


class ConfigValidationError(ValueError):
    """Raised when a config document fails validation.

    Carries *every* problem found, not just the first, so a form can highlight all
    the bad fields in one pass.
    """

    def __init__(self, errors: list[FieldError]) -> None:
        self.errors = errors
        detail = "; ".join(str(e) for e in errors)
        super().__init__(f"{len(errors)} validation error(s): {detail}")
