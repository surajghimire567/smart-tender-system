"""P2 request/response schemas. Fields are locked to Team AI Blueprint v1.1."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=254, pattern=_EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=72)
    company_name: str = Field(min_length=2, max_length=200)
    registration_number: str = Field(min_length=3, max_length=50)

    @field_validator("email", mode="before")
    @classmethod
    def lowercase_email(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def bcrypt_byte_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email", mode="before")
    @classmethod
    def lowercase_email(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    role: Literal["admin", "vendor"]
    expires_in: Literal[3600] = 3600


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: Literal["admin", "vendor"]
    company_name: str | None = None
    registration_number: str | None = None
    created_at: datetime


class VendorTenderItem(BaseModel):
    id: int
    title: str
    status: Literal["published"]
    deadline: datetime
    ceiling_price: Decimal
    is_open: bool
    has_my_bid: bool


class BidReceipt(BaseModel):
    bid_id: int
    tender_id: int
    bid_hash: str
    submitted_at: datetime
    supersedes_bid_id: int | None = None


class VendorTenderOut(BaseModel):
    id: int
    title: str
    description: str
    ceiling_price: Decimal
    deadline: datetime
    status: Literal["published", "closed", "awarded"]
    is_open: bool
    my_current_bid: BidReceipt | None = None


class BidIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class MyBidItem(BaseModel):
    bid_id: int
    tender_id: int
    tender_title: str
    tender_status: Literal["draft", "published", "closed", "awarded"]
    bid_hash: str
    submitted_at: datetime
    is_current: bool
    supersedes_bid_id: int | None = None


class VendorResultOut(BaseModel):
    tender_id: int
    status: Literal["closed", "awarded"]
    my_rank: int
    my_amount: Decimal
    total_bids: int
    outcome: Literal["pending", "won", "lost"]
