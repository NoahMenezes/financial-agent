"""Engine: one deterministic forecast per request (baseline + with-changes)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from .calendar import (
    build_daily_nets,
    project_recurring_occurrences,
    window_dates,
)
from .io_schema import adapt_request, adapt_state, validate_result, validate_spending_actions
from .models import ForecastResult
from .safety import build_base_balances
from .solver import amount_safe_to_pay, earliest_date_for_full_payment
from .income import merge_income, project_salary_occurrences
from .spending import plan_spending_candidates

WINDOW_DAYS = 90


def forecast_one(request_row: dict, agent1_state: dict, ctx: dict | None = None) -> ForecastResult:
    req = adapt_request(request_row)
    st = adapt_state(agent1_state)
    request_date = req["request_date"]
    window_end = request_date + timedelta(days=WINDOW_DAYS)
    dates = window_dates(request_date, WINDOW_DAYS)
    requested = req["requested_amount"]

    occurrences = project_recurring_occurrences(
        st["recurring_expenses"], request_date, window_end
    )
    # Recurring salary: Agent 1 forwards scheduled rows only; project the
    # monthly pay cycle from settled history (+ payroll amendments) here.
    # Without this, users with no scheduled row show zero future income.
    income_rows = st["confirmed_income"]
    if ctx is not None:
        projected = project_salary_occurrences(
            ctx["all_events"], ctx["messages"], req["user_id"],
            st["home_currency"], ctx["fx_idx"], ctx["ocr"],
            request_date, window_end,
        )
        income_rows = merge_income(st["confirmed_income"], projected,
                                   request_date, window_end)
    nets = build_daily_nets(
        income_rows, st["pending_debits"], occurrences,
        request_date, window_end,
    )
    base = build_base_balances(st["current_balance"], nets, dates)

    safe = amount_safe_to_pay(base, dates, st["minimum_balance"], requested, request_date)
    earliest = earliest_date_for_full_payment(base, dates, st["minimum_balance"], requested)
    validate_result(safe, earliest, requested, dates)

    # With-changes variant (SEPARATE): top-3 flexible savings applied.
    actions, stop_keys, reduce_map = plan_spending_candidates(
        st["recurring_expenses"], occurrences,
        st["reducible_cats"], st["stoppable_cats"], st["home_currency"],
    )
    if actions:
        validate_spending_actions(actions, st["recurring_expenses"])
        nets2 = build_daily_nets(
            income_rows, st["pending_debits"], occurrences,
            request_date, window_end, stop_series=stop_keys, reduce_to=reduce_map,
        )
        base2 = build_base_balances(st["current_balance"], nets2, dates)
        safe2 = amount_safe_to_pay(base2, dates, st["minimum_balance"], requested, request_date)
        earliest2 = earliest_date_for_full_payment(base2, dates, st["minimum_balance"], requested)
        validate_result(safe2, earliest2, requested, dates)
    else:
        safe2, earliest2 = safe, earliest
        base2 = base

    return ForecastResult(
        request_id=req["request_id"],
        user_id=req["user_id"],
        request_date=request_date,
        requested_amount=requested,
        home_currency=st["home_currency"],
        amount_safe_to_pay=safe,
        earliest_date_for_full_payment=earliest,
        safe_with_changes=safe2,
        earliest_with_changes=earliest2,
        spending_candidates=actions,
        daily_base=base,
        daily_dates=dates,
        daily_base2=base2,
    )
