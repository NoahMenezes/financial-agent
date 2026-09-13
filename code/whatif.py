"""What-if simulator CLI (differentiator, read-only demo).

Answers "what if I pay X on date D?" using the SAME deterministic safety
predicate as the pipeline (forecast.safety.is_safe_with_payments) over the
already-computed daily bases in code/state/forecasts.json.

Never writes output.csv. Stdlib only.

Usage:
  code/.venv/bin/python code/whatif.py --request request_28 --amount 500 --date 2025-08-10
  code/.venv/bin/python code/whatif.py --request request_28 --amount 1302.4 --date 2025-08-10 --currency EUR
  code/.venv/bin/python code/whatif.py --list request_28   # show bases + verdict context
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))
REPO_ROOT = CODE_DIR.parent

from forecast.safety import is_safe_with_payments  # noqa: E402


def _d(s: str) -> date:
    y, m, d = str(s)[:10].split("-")
    return date(int(y), int(m), int(d))


def main() -> int:
    ap = argparse.ArgumentParser(description="What-if payment safety check (read-only)")
    ap.add_argument("--request", required=True, help="request_id e.g. request_28")
    ap.add_argument("--amount", default=None, help="hypothetical payment amount")
    ap.add_argument("--date", default=None, help="hypothetical pay date YYYY-MM-DD")
    ap.add_argument("--currency", default="", help="label only (no conversion)")
    ap.add_argument("--list", dest="list_only", action="store_true",
                    help="show stored verdict + bases, no simulation")
    args = ap.parse_args()

    with open(CODE_DIR / "state" / "forecasts.json", encoding="utf-8") as fh:
        forecasts = json.load(fh)
    rec = forecasts.get(args.request)
    if not rec:
        print(f"unknown request_id {args.request} (run stage2 first)")
        return 2
    import csv
    states = json.load(open(CODE_DIR / "state" / "user_financial_states.json", encoding="utf-8"))
    st = states.get(rec["user_id"], {})
    minimum = Decimal(str(st.get("minimum_balance_to_keep", "0")))
    dates = [_d(s) for s in rec["daily_dates"]]
    base = [Decimal(s) for s in rec["daily_base"]]
    cur = rec.get("home_currency", args.currency or "")

    print(f"request {rec['request_id']} user {rec['user_id']} {cur}")
    print(f"stored: safe_today={rec['amount_safe_to_pay']} "
          f"earliest={rec.get('earliest_date_for_full_payment') or 'none'} "
          f"requested={rec['requested_amount']} min={minimum}")
    if args.list_only or args.amount is None:
        print(f"window: {dates[0]}..{dates[-1]} ({len(dates)} days)")
        return 0
    pay_date = _d(args.date) if args.date else _d(rec["request_date"])
    amt = Decimal(str(args.amount))
    if pay_date < dates[0] or pay_date > dates[-1]:
        print(f"outside 90d window [{dates[0]}..{dates[-1]}]; cannot judge")
        return 2
    safe = is_safe_with_payments(base, dates, {pay_date: amt}, minimum)
    print(f"what-if: pay {cur} {amt} on {pay_date} -> {'SAFE' if safe else 'UNSAFE'}")
    if not safe:
        # Find breach day for demo clarity.
        paid = Decimal("0")
        ordered = sorted([(pay_date, amt)])
        idx = 0
        for t, d in enumerate(dates):
            while idx < len(ordered) and ordered[idx][0] <= d:
                paid += ordered[idx][1]
                idx += 1
            if base[t] - paid < minimum:
                print(f"breach day {d}: projected {base[t]-paid} < min {minimum}")
                break
        ear = rec.get("earliest_date_for_full_payment") or "none-in-90d"
        print(f"hint: stored earliest full {rec['requested_amount']} is {ear}; "
              f"stored safe today is {rec['amount_safe_to_pay']}")
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
