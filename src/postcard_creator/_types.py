import dataclasses
from datetime import datetime
from typing import Any, Self


@dataclasses.dataclass(frozen=True, kw_only=True)
class Address:
    first_name: str
    last_name: str
    street: str
    zip_code: int
    place: str
    company: str = ""
    country: str = ""
    company_addition: str = ""
    salutation: str = ""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Quota:
    quota: int
    end: datetime
    retention_days: int
    available: bool
    next: datetime | None

    @classmethod
    def from_model(cls, model: dict[str, Any]) -> Self:
        try:
            next_ = datetime.fromisoformat(model["next"])
        except (KeyError, TypeError):
            next_ = None
        return cls(
            quota=int(model["quota"]),
            end=datetime.fromisoformat(model["end"]),
            retention_days=int(model["retentionDays"]),
            available=bool(model["available"]),
            next=next_,
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class OrderConfirmation:
    order_id: int

    @classmethod
    def from_model(cls, model: dict[str, Any]) -> Self:
        return cls(
            order_id=int(model["orderId"]),
        )
