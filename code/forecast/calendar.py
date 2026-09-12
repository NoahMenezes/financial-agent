"""Calendar: 90-day window + recurring projection + daily nets.

Deterministic: sorted I/O, Decimal money, no randomness.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

TWOPLACES = Decimal("0.01")


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = str(s).strip()[:10]
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def to_decimal(x) -> Decimal:
    """Float/str/int -> Decimal(2dp). Uses str() to avoid binary float error."""
    if isinstance(x, Decimal):
        return x.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return Decimal(str(x)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def window_dates(request_date: date, days: int = 90) -> list[date]:
    return [request_date + timedelta(days=i) for i in range(days + 1)]


def project_recurring_occurrences(
    series_list: list,
    request_date: date,
    window_end: date,
) -> list[dict]:
    """Expand each history-backed recurring series forward by median interval.

    Starts from series last_date and steps by interval_days until past
    window_end. Keeps occurrences with request_date <= d <= window_end.
    Each occurrence: {date, amount, series_key, category, essential,
    flexible, representative_event_id}.
    """
    occ: list[dict] = []
    for s in series_list:
        interval = int(s["median_interval_days"])
        if interval <= 0:
            continue
        last = parse_date(s["last_date"]) if isinstance(s["last_date"], str) else s["last_date"]
        if last is None:
            continue
        try:
            amt = to_decimal(s["forecast_amount"])
        except Exception:
            continue
        d = last
        # Guard against pathological intervals/loops.
        steps = 0
        while d <= window_end and steps < 20:
            d = d + timedelta(days=interval)
            steps += 1
            if d < request_date or d > window_end:
                continue
            occ.append({
                "date": d,
                "amount": amt,
                "series_key": s["series_key"],
                "category": s["category"],
                "essential": bool(s.get("essential", True)),
                "flexible": bool(s.get("flexible", False)),
                "representative_event_id": s.get("representative_event_id", ""),
            })
    occ.sort(key=lambda o: (o["date"], o["series_key"]))
    return occ


def build_daily_nets(
    confirmed_income: list[dict],
    pending_debits: list[dict],
    occurrences: list[dict],
    request_date: date,
    window_end: date,
    stop_series: set[str] | None = None,
    reduce_to: dict[str, Decimal] | None = None,
) -> dict[date, Decimal]:
    """Net cash per day: +income, -debits, -recurring.

    - Income counted only on settlement_date if within [request_date, window_end].
    - Pending/scheduled debits reserved on settlement_date; overdue
      (settle < request_date) clamped to request_date (safer).
    - stop_series: drop all occurrences of those series_keys.
    - reduce_to: cap each occurrence of series_key at new per-occurrence amount.
    """
    stop_series = stop_series or set()
    reduce_to = reduce_to or {}
    nets: dict[date, Decimal] = {}

    def add(d: date | None, amt: Decimal) -> None:
        if d is None:
            return
        if d < request_date or d > window_end:
            return
        nets[d] = nets.get(d, Decimal("0.00")) + amt

    for inc in confirmed_income:
        sd = parse_date(inc.get("settlement_date"))
        try:
            amt = to_decimal(inc.get("amount_home", 0))
        except Exception:
            continue
        if amt <= 0:
            continue
        add(sd, amt)

    for deb in pending_debits:
        sd = parse_date(deb.get("settlement_date"))
        try:
            amt = to_decimal(deb.get("amount_home", 0))
        except Exception:
            continue
        if amt <= 0:
            continue
        if sd is None:
            continue
        if sd < request_date:
            sd = request_date
        add(sd, -amt)

    for o in occurrences:
        if o["series_key"] in stop_series:
            continue
        d = o["date"]
        amt = o["amount"]
        if o["series_key"] in reduce_to:
            cap = reduce_to[o["series_key"]]
            amt = cap if cap < amt else amt
        add(d, -amt)

    return nets
