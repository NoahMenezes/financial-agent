"""Solver: amount_safe_to_pay (binary search) + earliest_date (linear scan)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .safety import is_safe_with_payments

CENT = Decimal("0.01")


def _to_cents(d: Decimal) -> int:
    q = d.quantize(CENT, rounding=ROUND_HALF_UP)
    return int((q * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _to_decimal(cents: int) -> Decimal:
    return (Decimal(cents) / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)


def amount_safe_to_pay(
    base_balances: list[Decimal],
    dates: list[date],
    min_balance: Decimal,
    requested_amount: Decimal,
    pay_date: date | None = None,
) -> Decimal:
    """Largest amount payable on pay_date (default D0) keeping 90d safety.

    Binary search over integer cents in [0, requested]. Monotone predicate.
    Always 0 <= result <= requested.
    """
    if requested_amount <= 0:
        return Decimal("0.00")
    if not dates:
        return Decimal("0.00")
    target = pay_date or dates[0]
    req_cents = _to_cents(requested_amount)
    # Fast paths.
    if is_safe_with_payments(base_balances, dates, {target: requested_amount}, min_balance):
        return _to_decimal(req_cents)
    if not is_safe_with_payments(base_balances, dates, {target: CENT}, min_balance):
        # Even 1 cent breaks safety -> 0 (but double check 0 itself is safe;
        # baseline may already violate minimum, then 0 is still the answer).
        return Decimal("0.00")
    lo, hi = 1, req_cents
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if is_safe_with_payments(base_balances, dates, {target: _to_decimal(mid)}, min_balance):
            lo = mid
        else:
            hi = mid - 1
    return _to_decimal(lo)


def earliest_date_for_full_payment(
    base_balances: list[Decimal],
    dates: list[date],
    min_balance: Decimal,
    requested_amount: Decimal,
) -> date | None:
    """First date in window where full requested_amount as single payment is safe."""
    if requested_amount <= 0:
        return dates[0] if dates else None
    for d in dates:
        if is_safe_with_payments(base_balances, dates, {d: requested_amount}, min_balance):
            return d
    return None
