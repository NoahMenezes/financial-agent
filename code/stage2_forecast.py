"""Stage 2 -- 90-day forecast engine. Pure deterministic Python, no LLM calls.

Reads code/state/user_financial_states.json + dataset/requests.csv, writes
code/state/forecasts.json keyed by request_id (includes daily bases so Stage 3
can re-verify safety from files alone without recomputing).
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))

from common import FORECASTS_JSON, STATES_JSON, STATE_DIR, load_requests  # noqa: E402
from forecast.engine import forecast_one  # noqa: E402
from state_builder import build_fx_index, load_events, load_messages, load_rates  # noqa: E402
import vision_extract  # noqa: E402


def _fr_to_record(fr) -> dict:
    return {
        "request_id": fr.request_id,
        "user_id": fr.user_id,
        "request_date": fr.request_date.isoformat(),
        "requested_amount": str(fr.requested_amount),
        "home_currency": fr.home_currency,
        "amount_safe_to_pay": str(fr.amount_safe_to_pay),
        "earliest_date_for_full_payment": fr.earliest_date_for_full_payment.isoformat() if fr.earliest_date_for_full_payment else "",
        "safe_with_changes": str(fr.safe_with_changes),
        "earliest_with_changes": fr.earliest_with_changes.isoformat() if fr.earliest_with_changes else "",
        "spending_candidates": list(fr.spending_candidates),
        "daily_dates": [d.isoformat() for d in fr.daily_dates],
        "daily_base": [str(b) for b in fr.daily_base],
        "daily_base2": [str(b) for b in (fr.daily_base2 or fr.daily_base)],
    }


def run_forecast() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATES_JSON, encoding="utf-8") as fh:
        states = json.load(fh)
    requests = load_requests()
    ctx = {"all_events": load_events(), "messages": load_messages(),
           "fx_idx": build_fx_index(load_rates()), "ocr": vision_extract.to_ocr_compat()}
    out: dict = {}
    for req in requests:
        st = states.get(req["user_id"])
        if st is None:
            out[req["request_id"]] = {"request_id": req["request_id"], "user_id": req["user_id"],
                                      "request_date": req["request_date"],
                                      "requested_amount": str(req["requested_amount"]),
                                      "home_currency": "", "error": "missing_state"}
            continue
        fr = forecast_one(req, st, ctx)
        out[fr.request_id] = _fr_to_record(fr)
    # Bounds guard before writing.
    for rid, rec in out.items():
        if "error" in rec:
            continue
        safe = Decimal(rec["amount_safe_to_pay"])
        req_amt = Decimal(rec["requested_amount"])
        assert Decimal("0") <= safe <= req_amt, f"bounds fail {rid}"
    with open(FORECASTS_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    return out


def main() -> int:
    out = run_forecast()
    print(f"stage2: wrote {len(out)} forecasts -> {FORECASTS_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
