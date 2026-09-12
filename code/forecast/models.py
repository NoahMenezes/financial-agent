"""Shared dataclasses for Agent 2. All money uses Decimal (2dp)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class RecurringSeries:
    series_key: str
    category: str
    essential: bool
    flexible: bool
    flexibility: str
    protected: bool
    interval_days: int
    forecast_amount: Decimal
    minimum_allowed: Decimal | None
    last_date: date
    representative_event_id: str


@dataclass(frozen=True)
class ConfirmedIncome:
    event_id: str
    amount: Decimal
    settlement_date: date | None


@dataclass(frozen=True)
class PendingDebit:
    event_id: str
    amount: Decimal
    settlement_date: date | None
    status: str


@dataclass
class ForecastResult:
    request_id: str
    user_id: str
    request_date: date
    requested_amount: Decimal
    home_currency: str
    # Baseline (no spending changes) — contract for Agent 3.
    amount_safe_to_pay: Decimal = field(default_factory=lambda: Decimal("0.00"))
    earliest_date_for_full_payment: date | None = None
    # With-changes variant (SEPARATE result, flexible only, max 3 actions).
    safe_with_changes: Decimal = field(default_factory=lambda: Decimal("0.00"))
    earliest_with_changes: date | None = None
    spending_candidates: list[str] = field(default_factory=list)
    # Daily baseline balances D0..D90 before any request payment (for grounding).
    daily_base: list[Decimal] = field(default_factory=list)
    daily_dates: list[date] = field(default_factory=list)
    # Daily balances with the spending-candidate actions applied (Agent 3
    # verifies with-changes installment/partial plans against these).
    # Empty when no actions exist (then identical to daily_base).
    daily_base2: list[Decimal] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        def fmt(d: Decimal) -> float:
            return float(d)
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "request_date": self.request_date.isoformat(),
            "requested_amount": fmt(self.requested_amount),
            "home_currency": self.home_currency,
            "amount_safe_to_pay": fmt(self.amount_safe_to_pay),
            "earliest_date_for_full_payment": (
                self.earliest_date_for_full_payment.isoformat()
                if self.earliest_date_for_full_payment else ""
            ),
            "safe_with_changes": fmt(self.safe_with_changes),
            "earliest_with_changes": (
                self.earliest_with_changes.isoformat()
                if self.earliest_with_changes else ""
            ),
            "spending_candidates": list(self.spending_candidates),
        }
