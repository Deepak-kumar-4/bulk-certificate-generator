from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings


class JobCreate(BaseModel):
    """Request body for POST /api/jobs/.

    Only request-level rules live here. Recipients are deliberately loose (`Any`) so that a
    single malformed recipient never rejects the whole request; each one is validated by
    app.services.validation instead.
    """

    event_name: str = Field(examples=["Python Bootcamp 2026"])
    issuer_name: str = Field(examples=["Deetag Academy"])
    issue_date: date = Field(examples=["2026-10-01"])
    recipients: list[Any] = Field(
        examples=[
            [
                {"name": "Asha Rao", "email": "asha@example.com"},
                {"name": "", "email": "not-an-email"},
            ]
        ]
    )

    @field_validator("event_name", "issuer_name")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("recipients")
    @classmethod
    def recipients_within_bounds(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("must contain at least one recipient")
        limit = get_settings().max_recipients
        if len(value) > limit:
            raise ValueError(f"must contain at most {limit} recipients (got {len(value)})")
        return value


class JobCreated(BaseModel):
    id: str
    status: str
    total_count: int
    accepted_count: int
    invalid_count: int
    status_url: str
