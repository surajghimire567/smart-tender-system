"""Admin-facing audit log response shapes."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int | None
    actor_id: int | None
    action: str
    timestamp: datetime
    ip_address: str | None
    details: dict[str, Any] | None


class AuditLogPageOut(BaseModel):
    items: list[AuditLogOut]
    total: int
    limit: int
    offset: int
