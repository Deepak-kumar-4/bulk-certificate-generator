"""Recipient-level validation.

Pure functions: no database, no HTTP. A row that fails here is stored as INVALID with the
reason; it never causes the whole request to be rejected.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from email_validator import EmailNotValidError, validate_email

NAME_MAX_LENGTH = 100
DUPLICATE_EMAIL = "duplicate email in request"


@dataclass(frozen=True)
class RecipientResult:
    """Outcome of validating one recipient.

    For a valid row, `name` is trimmed and `email` is normalised and lowercased. For an
    invalid row they hold the values exactly as received (when they were strings), so the
    client can see what was rejected.
    """

    name: str | None
    email: str | None
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def error(self) -> str | None:
        return "; ".join(self.errors) if self.errors else None


def _as_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _check_name(value: Any) -> tuple[str | None, str | None]:
    """Return (clean_name, error)."""
    if value is None:
        return None, "name is required"
    if not isinstance(value, str):
        return None, "name must be a string"
    name = value.strip()
    if not name:
        return None, "name is required"
    if len(name) > NAME_MAX_LENGTH:
        return None, f"name must be at most {NAME_MAX_LENGTH} characters"
    return name, None


def _check_email(value: Any) -> tuple[str | None, str | None]:
    """Return (clean_email, error)."""
    if value is None:
        return None, "email is required"
    if not isinstance(value, str):
        return None, "email must be a string"
    if not value.strip():
        return None, "email is required"
    try:
        result = validate_email(value.strip(), check_deliverability=False)
    except EmailNotValidError:
        return None, "email is not valid"
    return result.normalized.lower(), None


def validate_recipient(raw: Any, seen_emails: set[str] | None = None) -> RecipientResult:
    """Validate a single recipient, collecting every problem rather than stopping at the first.

    `seen_emails` holds the emails already taken by earlier valid rows of the same request.
    """
    if not isinstance(raw, dict):
        return RecipientResult(name=None, email=None, errors=["recipient must be an object"])

    name, name_error = _check_name(raw.get("name"))
    email, email_error = _check_email(raw.get("email"))
    errors = [e for e in (name_error, email_error) if e]
    if email is not None and seen_emails is not None and email in seen_emails:
        errors.append(DUPLICATE_EMAIL)

    if errors:
        return RecipientResult(
            name=_as_text(raw.get("name")), email=_as_text(raw.get("email")), errors=errors
        )
    return RecipientResult(name=name, email=email)


def validate_recipients(raws: Iterable[Any]) -> list[RecipientResult]:
    """Validate every recipient of a request, including duplicate-email detection.

    The first valid row with a given email keeps it; any later row with the same email is
    marked INVALID. A row that is invalid for another reason does not claim the email.
    """
    seen_emails: set[str] = set()
    results: list[RecipientResult] = []
    for raw in raws:
        result = validate_recipient(raw, seen_emails)
        if result.is_valid:
            seen_emails.add(result.email)
        results.append(result)
    return results
