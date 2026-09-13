"""Agent 3A -- decision logic (pure deterministic, no LLM).

Consumes Agent 1 states (state_builder) + Agent 2 ForecastResult
(forecast package) and implements PART A exactly:
  * eligibility gates per payment method,
  * LOCKED installment duration: whole months between the matched option's
    first and last payment dates (common.months_span) <= max_installment_months,
  * 6-step ranking, status mapping, spending-change and plan formats,
  * grounded plain-language explanations.

amount_safe_to_pay / earliest_date_for_full_payment outputs are ALWAYS the
no-spending-changes baseline (spec); with-changes numbers only unlock
affordable_with_plan candidates.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from forecast.safety import is_safe_with_payments


def rank_key(c):
    """6-step ranking (LOCKED order). Rule 1 (completes by deadline) beats
    rule 2 (no spending changes): a completing plan with changes sorts before
    a non-completing plan without changes. Exported for unit tests."""
    return (0 if c["completes"] else 1,
            0 if not c["changes"] else 1,
            c["total"], c["start"], c["n"], c["option_id"] or "~")


def _d(s):
    if isinstance(s, date):
        return s
    if not s:
        return None
    try:
        y, m, d = str(s)[:10].split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def fmt_minimal(x: Decimal) -> str:
    """amount_safe_to_pay style: strip all trailing zeros ('603.3')."""
    q = x.quantize(Decimal("0.01"))
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def fmt_plan(x: Decimal) -> str:
    """payment_plan style: 2dp, strip only '.00' ('620.40' stays)."""
    q = Decimal(str(x)).quantize(Decimal("0.01"))
    s = format(q, "f")
    if s.endswith(".00"):
        s = s[:-3]
    return s


def months_needed_option(first: date, n: int, freq_days: int) -> int:
    """LOCKED #1: whole months between first and last payment date.

    Derived from the matched option's real dates, NOT payment count.
    Single-payment options span 0 months.
    """
    if n <= 1 or not freq_days:
        return 0
    try:
        from common import installment_last_date, months_span
    except ImportError:  # pragma: no cover - fallback when run as package
        from code.common import installment_last_date, months_span  # type: ignore
    last = installment_last_date(first, n, freq_days)
    return months_span(first, last)


def installment_schedule(opt: dict):
    """Expand an installment option to [(date, Decimal amount)] exactly."""
    n = int(opt["number_of_payments"])
    first = _d(opt["first_payment_date"])
    freq = int(opt["payment_frequency_days"]) if (opt.get("payment_frequency_days") or "").strip() else 0
    amt = Decimal(str(opt["payment_amount"]))
    return [(first + timedelta(days=k * freq) if freq else first, amt) for k in range(n)]


def decide_request(agent1_state: dict, request: dict, fr, options: list) -> dict:
    """agent1_state: state_builder dict. fr: ForecastResult. options: rows."""
    req_date = _d(request["request_date"])
    desired = _d(request["desired_completion_date"])
    requested = Decimal(str(request["requested_amount"]))
    allows_partial = str(request.get("allows_partial_payment", "")).lower() == "true"
    methods = set(agent1_state.get("payment_methods_user_will_consider") or [])
    max_raw = (agent1_state.get("max_installment_months") or "")
    max_raw = str(max_raw).strip()
    max_m = int(max_raw) if max_raw.isdigit() else None
    home = agent1_state.get("home_currency", "")
    minimum = Decimal(str(agent1_state["minimum_balance_to_keep"]))

    safe = fr.amount_safe_to_pay
    earliest = fr.earliest_date_for_full_payment
    dates, base = fr.daily_dates, fr.daily_base
    base2 = fr.daily_base2 or base
    wc_actions = list(fr.spending_candidates or [])

    def ok(payments: dict, with_changes: bool = False) -> bool:
        b = base2 if with_changes else base
        try:
            return is_safe_with_payments(b, dates, payments, minimum)
        except ValueError:
            return False

    candidates = []
    # ---- full_payment (baseline, then with-changes) ----
    if "full_payment" in methods:
        for opt in options:
            if opt.get("payment_method") != "full_payment":
                continue
            total = Decimal(str(opt["total_payable_amount"]))
            if safe >= requested and ok({req_date: requested}):
                candidates.append({"method": "full_payment",
                                   "option_id": opt["payment_option_id"],
                                   "plan": [(req_date, requested)], "total": total,
                                   "start": req_date, "n": 1, "changes": [],
                                   "completes": req_date <= desired})
            if wc_actions and ok({req_date: requested}, with_changes=True):
                candidates.append({"method": "full_payment",
                                   "option_id": opt["payment_option_id"],
                                   "plan": [(req_date, requested)], "total": total,
                                   "start": req_date, "n": 1,
                                   "changes": list(wc_actions),
                                   "completes": req_date <= desired})
            break
    # ---- partial_payment (baseline only) ----
    if allows_partial and "partial_payment" in methods \
            and Decimal("0") < safe < requested \
            and earliest is not None and earliest <= desired:
        remainder = requested - safe
        joint = {req_date: safe}
        joint[earliest] = joint.get(earliest, Decimal("0")) + remainder
        if ok(joint):
            candidates.append({"method": "partial_payment", "option_id": "",
                               "plan": [(req_date, safe), (earliest, remainder)],
                               "total": requested, "start": req_date, "n": 2,
                               "changes": [], "completes": True})
    # ---- installments (each option, baseline then with-changes) ----
    if "installments" in methods and max_m is not None:
        window_end = dates[-1] if dates else req_date
        for opt in sorted(options, key=lambda o: o["payment_option_id"]):
            if opt.get("payment_method") != "installments":
                continue
            n = int(opt["number_of_payments"])
            freq = int(opt["payment_frequency_days"]) if (opt.get("payment_frequency_days") or "").strip() else 0
            first = _d(opt["first_payment_date"])
            if first is None or months_needed_option(first, n, freq) > max_m:
                continue
            sched = installment_schedule(opt)
            if any(d < req_date or d > window_end for d, _ in sched):
                continue
            total = Decimal(str(opt["total_payable_amount"]))
            extra = {}
            for d, a in sched:
                extra[d] = extra.get(d, Decimal("0")) + a
            last_d = max(d for d, _ in sched)
            if ok(extra):
                candidates.append({"method": "installments",
                                   "option_id": opt["payment_option_id"],
                                   "plan": sched, "total": total,
                                   "start": min(d for d, _ in sched),
                                   "n": len(sched), "changes": [],
                                   "completes": last_d <= desired})
            elif wc_actions and ok(extra, with_changes=True):
                candidates.append({"method": "installments",
                                   "option_id": opt["payment_option_id"],
                                   "plan": sched, "total": total,
                                   "start": min(d for d, _ in sched),
                                   "n": len(sched), "changes": list(wc_actions),
                                   "completes": last_d <= desired})
    # ---- wait (baseline) ----
    if "full_payment" in methods and earliest is not None and earliest > req_date:
        candidates.append({"method": "wait", "option_id": "",
                           "plan": [(earliest, requested)], "total": requested,
                           "start": earliest, "n": 1, "changes": [],
                           "completes": earliest <= desired})

    candidates.sort(key=rank_key)
    winner = candidates[0] if candidates else None

    earliest_out = earliest.isoformat() if earliest is not None else ""
    if winner is None:
        status, method = "not_affordable", "not_recommended"
        plan_str, changes_str = "none", "none"
    else:
        method = winner["method"]
        plan_str = "|".join(f"{d.isoformat()}:{fmt_plan(a)}" for d, a in sorted(winner["plan"]))
        changes_str = "|".join(winner["changes"]) if winner["changes"] else "none"
        if method == "wait":
            status = "affordable_later"
        elif method in ("partial_payment", "installments") or winner["changes"]:
            status = "affordable_with_plan"
        else:
            status = "affordable_now"

    return {
        "request_id": request["request_id"],
        "amount_safe_to_pay": fmt_minimal(safe),
        "affordability_status": status,
        "recommended_payment_method": method,
        "payment_plan": plan_str,
        "earliest_date_for_full_payment": earliest_out,
        "spending_changes_needed": changes_str,
        "decision_explanation": build_explanation(
            method, winner, request, home,
            fmt_minimal(minimum), fmt_minimal(safe), earliest_out),
    }


def build_explanation(method, winner, request, home, minimum, safe_s, earliest_s) -> str:
    requested = fmt_minimal(Decimal(str(request["requested_amount"])))
    if method == "not_recommended":
        return (f"Cannot safely afford {home} {requested} within 90 days. "
                f"Paying more than {home} {safe_s} today would take the "
                f"balance below the {home} {minimum} minimum.")
    if method == "full_payment" and not (winner and winner["changes"]):
        return (f"Pay {home} {requested} today. This leaves at least "
                f"{home} {minimum} available over the next 90 days.")
    if method == "full_payment":
        return (f"{describe_changes(winner['changes'])}, then pay {home} {requested} "
                f"today. This leaves at least {home} {minimum} available.")
    if method == "partial_payment":
        d2 = sorted(winner["plan"])[1][0].isoformat()
        rem = fmt_minimal(sorted(winner["plan"])[1][1])
        return (f"Pay {home} {safe_s} today and the remaining {home} {rem} on {d2}. "
                f"This completes the full request and keeps the {home} {minimum} "
                f"minimum protected.")
    if method == "installments":
        n = len(winner["plan"])
        amt = fmt_minimal(sorted(winner["plan"])[0][1])
        start = sorted(winner["plan"])[0][0].isoformat()
        return (f"Use {n} installments of {home} {amt}, starting {start}. "
                f"This leaves at least {home} {minimum} available.")
    if method == "wait":
        return (f"Pay {home} {requested} in full on {earliest_s}. Paying earlier "
                f"would take the balance below the {home} {minimum} minimum.")
    return f"See payment plan. Minimum {home} {minimum} protected."


def describe_changes(changes: list) -> str:
    bits = []
    for c in changes:
        p = c.split(":")
        bits.append(f"Stop {p[1]}" if p[0] == "stop" else f"Reduce {p[1]} to {p[2]}")
    s = " and ".join(bits)
    return s[0].upper() + s[1:] if s else "Adjust spending"
