"""P1-owned request and response models for tender administration."""
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
        value = value.astimezone(timezone.utc)
        if value <= datetime.now(timezone.utc):
            raise ValueError("deadline must be in the future")
        return value

    @model_validator(mode="after")
    def ceiling_must_cover_base_price(self):
        if self.ceiling_price < self.base_price:
            raise ValueError("ceiling_price must be greater than or equal to base_price")
        return self


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
        value = value.astimezone(timezone.utc)
        if value <= datetime.now(timezone.utc):
            raise ValueError("deadline must be in the future")
        return value

    @model_validator(mode="after")
    def ceiling_must_cover_base_price(self):
        if (
            self.base_price is not None
            and self.ceiling_price is not None
            and self.ceiling_price < self.base_price
        ):
            raise ValueError("ceiling_price must be greater than or equal to base_price")
        return self


class TenderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int
    title: str
    description: str
    base_price: Decimal
    ceiling_price: Decimal
    deadline: datetime
    closed_at: datetime | None = None
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
    vendor_id_b: int | None
    flag_reason: str
    flagged_at: datetime
