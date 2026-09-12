"""Adapters: Agent 1 state + request row -> validated Agent 2 inputs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .calendar import parse_date, to_decimal


def adapt_request(row: dict) -> dict:
    rd = parse_date(row.get("request_date"))
    dd = parse_date(row.get("desired_completion_date"))
    if rd is None:
        raise ValueError(f"bad request_date: {row}")
    try:
        req_amt = to_decimal(row.get("requested_amount", 0))
    except Exception as exc:
        raise ValueError(f"bad requested_amount: {row}") from exc
    allows = str(row.get("allows_partial_payment", "")).strip().lower() == "true"
    return {
        "request_id": row["request_id"],
        "user_id": row["user_id"],
        "request_date": rd,
        "desired_completion_date": dd,
        "requested_amount": req_amt,
        "allows_partial_payment": allows,
    }


def adapt_state(state: dict) -> dict:
    try:
        current = to_decimal(state["current_balance"])
        minimum = to_decimal(state["minimum_balance_to_keep"])
    except Exception as exc:
        raise ValueError("state missing balances") from exc
    home = str(state.get("home_currency", "")).strip()
    recurring = state.get("recurring_expenses", []) or []
    income = state.get("confirmed_future_income", []) or []
    debits = state.get("pending_scheduled_debits", []) or []
    return {
        "home_currency": home,
        "current_balance": current,
        "minimum_balance": minimum,
        "recurring_expenses": recurring,
        "confirmed_income": income,
        "pending_debits": debits,
        "reducible_cats": set(state.get("reducible_categories", []) or []),
        "stoppable_cats": set(state.get("stoppable_categories", []) or []),
        "protected_cats": set(state.get("protected_categories", []) or []),
    }


def validate_result(safe: Decimal, earliest: date | None, requested: Decimal,
                    dates: list[date]) -> None:
    if not (Decimal("0.00") <= safe <= requested):
        raise AssertionError(f"safe {safe} out of [0, {requested}]")
    if earliest is not None and earliest not in dates:
        raise AssertionError(f"earliest {earliest} outside 90d window")


def validate_spending_actions(actions: list[str], recurring: list[dict]) -> None:
    if len(actions) > 3:
        raise AssertionError("more than 3 spending actions")
    seen: set[str] = set()
    flex_ids = {s.get("representative_event_id") for s in recurring if s.get("flexible")}
    for a in actions:
        parts = a.split(":")
        if parts[0] == "stop" and len(parts) == 2:
            eid = parts[1]
            if eid in seen:
                raise AssertionError(f"duplicate event {eid}")
            seen.add(eid)
            if eid not in flex_ids:
                raise AssertionError(f"stop targets non-flexible {eid}")
        elif parts[0] == "reduce_to" and len(parts) == 3:
            eid = parts[1]
            if eid in seen:
                raise AssertionError(f"duplicate event {eid}")
            seen.add(eid)
            if eid not in flex_ids:
                raise AssertionError(f"reduce targets non-flexible {eid}")
            Decimal(parts[2])  # must parse
        else:
            raise AssertionError(f"bad action format: {a}")
