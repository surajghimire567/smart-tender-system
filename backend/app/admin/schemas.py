"""P1-owned request and response models for tender administration."""
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TenderCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    description: str
    base_price: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    ceiling_price: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    deadline: datetime

    @field_validator("deadline")
    @classmethod
    def deadline_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline must include a timezone")
        return value.astimezone(timezone.utc)


class TenderUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    base_price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    ceiling_price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    deadline: datetime | None = None

    @field_validator("deadline")
    @classmethod
    def deadline_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadline must include a timezone")
        return value.astimezone(timezone.utc)


class TenderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int
    title: str
    description: str
    base_price: Decimal
    ceiling_price: Decimal
    deadline: datetime
    status: str
    created_at: datetime
    is_open: bool


class AwardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    winning_bid_id: int = Field(gt=0)


class AwardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int
    winning_bid_id: int
    awarded_at: datetime


class CollusionFlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int
    vendor_id_a: int
    vendor_id_b: int
    flag_reason: str
    flagged_at: datetime
