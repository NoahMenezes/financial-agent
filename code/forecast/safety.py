"""Safety predicate: balance must never fall below minimum over 90 days."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

EPS = Decimal("0.000001")


def build_base_balances(
    current_balance: Decimal,
    daily_nets: dict[date, Decimal],
    dates: list[date],
) -> list[Decimal]:
    """Cumulative baseline balances D0..D90 before any request payment."""
    balances: list[Decimal] = []
    running = current_balance
    for d in dates:
        running = running + daily_nets.get(d, Decimal("0.00"))
        balances.append(running)
    return balances


def is_safe_with_payments(
    base_balances: list[Decimal],
    dates: list[date],
    payments: dict[date, Decimal],
    min_balance: Decimal,
) -> bool:
    """True iff base[t] - paid_so_far[t] >= min_balance for every t.

    payments: {pay_date: amount}. Multiple payments allowed (installments,
    partial legs). Deterministic: sorted pay dates.
    """
    if not base_balances or not dates or len(base_balances) != len(dates):
        raise ValueError("base_balances and dates must align")
    ordered = sorted(payments.items(), key=lambda kv: kv[0])
    paid_so_far = Decimal("0.00")
    idx = 0
    for t, d in enumerate(dates):
        while idx < len(ordered) and ordered[idx][0] <= d:
            paid_so_far += ordered[idx][1]
            idx += 1
        if base_balances[t] - paid_so_far < min_balance - EPS:
            return False
    return True


def min_projected_balance(
    base_balances: list[Decimal],
    dates: list[date],
    payments: dict[date, Decimal] | None = None,
) -> Decimal:
    payments = payments or {}
    ordered = sorted(payments.items(), key=lambda kv: kv[0])
    paid = Decimal("0.00")
    idx = 0
    worst: Decimal | None = None
    for t, d in enumerate(dates):
        while idx < len(ordered) and ordered[idx][0] <= d:
            paid += ordered[idx][1]
            idx += 1
        bal = base_balances[t] - paid
        worst = bal if worst is None or bal < worst else worst
    return worst if worst is not None else Decimal("0.00")
