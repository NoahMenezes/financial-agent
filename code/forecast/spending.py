"""Spending-changes variant: flexible recurring only, max 3 actions, separate result."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .calendar import to_decimal

ZERO_DECIMAL_CURRENCIES = {"IDR", "INR", "ZAR"}


def format_spending_amount(value: Decimal, home_currency: str) -> str:
    q = value.quantize(Decimal("0.01"))
    if home_currency in ZERO_DECIMAL_CURRENCIES:
        return str(int(q.to_integral_value(rounding="ROUND_HALF_UP")))
    return format(q, ".2f")


def _parse_min_allowed(raw) -> Decimal | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        v = to_decimal(s)
    except Exception:
        return None
    return v if v > 0 else None


def plan_spending_candidates(
    recurring_expenses: list[dict],
    occurrences: list[dict],
    reducible_cats: set[str],
    stoppable_cats: set[str],
    home_currency: str,
    max_actions: int = 3,
) -> tuple[list[str], set[str], dict[str, Decimal]]:
    """Rank flexible series by 90d window savings. Return (actions, stop_keys, reduce_map).

    - can_reduce: cat in reducible AND flexibility allows reduce AND valid min < forecast.
    - can_stop: cat in stoppable AND flexibility allows stop.
    - flexibility 'mixed' trusts category permission.
    - Picks max-savings action per series, ranks series by savings desc,
      event_id asc (deterministic), takes top `max_actions`.
    - Action strings use representative_event_id (a real flexible recurring row).
    """
    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for o in occurrences:
        if not o.get("flexible"):
            continue
        totals[o["series_key"]] = totals.get(o["series_key"], Decimal("0.00")) + o["amount"]
        counts[o["series_key"]] = counts.get(o["series_key"], 0) + 1

    by_key = {s["series_key"]: s for s in recurring_expenses}
    scored: list[tuple[Decimal, str, str, str, Decimal | None]] = []
    # (savings, series_key, action, event_id, new_amount_or_None)
    for key, total in totals.items():
        s = by_key.get(key)
        if not s or not s.get("flexible"):
            continue
        cat = s["category"]
        flex = str(s.get("flexibility", ""))
        eid = s.get("representative_event_id", "")
        if not eid:
            continue
        try:
            forecast = to_decimal(s["forecast_amount"])
        except Exception:
            continue
        allows_reduce_flag = flex in ("reducible", "reducible_or_stoppable", "mixed")
        allows_stop_flag = flex in ("stoppable", "reducible_or_stoppable", "mixed")
        can_reduce_cat = cat in reducible_cats
        can_stop_cat = cat in stoppable_cats
        min_allowed = _parse_min_allowed(s.get("minimum_allowed_amount"))

        save_stop = total if (can_stop_cat and allows_stop_flag) else Decimal("-1")
        save_reduce = Decimal("-1")
        if can_reduce_cat and allows_reduce_flag and min_allowed is not None and min_allowed < forecast:
            per = forecast - min_allowed
            save_reduce = per * counts.get(key, 0)

        if save_stop < 0 and save_reduce < 0:
            continue
        if save_stop >= save_reduce:
            scored.append((save_stop, key, "stop", eid, None))
        else:
            assert min_allowed is not None
            scored.append((save_reduce, key, "reduce", eid, min_allowed))

    scored.sort(key=lambda t: (-t[0], t[3]))
    chosen = scored[:max_actions]
    actions: list[str] = []
    stop_keys: set[str] = set()
    reduce_map: dict[str, Decimal] = {}
    for _, key, action, eid, new_amt in chosen:
        if action == "stop":
            actions.append(f"stop:{eid}")
            stop_keys.add(key)
        else:
            assert new_amt is not None
            actions.append(f"reduce_to:{eid}:{format_spending_amount(new_amt, home_currency)}")
            reduce_map[key] = new_amt
    return actions, stop_keys, reduce_map
