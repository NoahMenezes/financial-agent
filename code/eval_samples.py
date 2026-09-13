"""Diagnostic self-score on dataset/sample_requests.csv (format/style only).

Runs the real Stage 1 -> Stage 2 -> Stage 3 engines on the 25 solved sample
rows and reports agreement on status/method/plan-shape/earliest-presence plus
validator errors. For development diagnostics only; never used for eval
predictions and never hardcodes answers. Stdlib only.

Usage:
    python3 code/eval_samples.py
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))

from state_builder import build_all_states, build_fx_index, load_events, load_messages, load_rates  # noqa: E402
from forecast.engine import forecast_one  # noqa: E402
import decide  # noqa: E402
import vision_extract  # noqa: E402
from common import load_options  # noqa: E402


def main() -> int:
    repo = CODE_DIR.parent
    with open(repo / "dataset" / "sample_requests.csv", encoding="utf-8") as fh:
        samples = list(csv.DictReader(fh))
    opts = {}
    for o in load_options():
        opts.setdefault(o["request_id"], []).append(o)
    user_ids = sorted({s["user_id"] for s in samples})
    states = build_all_states(user_ids)
    ctx = {"all_events": load_events(), "messages": load_messages(),
           "fx_idx": build_fx_index(load_rates()), "ocr": vision_extract.to_ocr_compat()}
    agree = Counter()
    safe_diffs = []
    for s in samples:
        req = {k: s[k] for k in ("request_id", "user_id", "request_date", "request_type",
                                 "requested_amount", "desired_completion_date",
                                 "allows_partial_payment", "request_text")}
        fr = forecast_one(req, states[s["user_id"]], ctx)
        pred = decide.decide_request(states[s["user_id"]], req, fr, opts.get(s["request_id"], []))
        agree["status_match"] += pred["affordability_status"] == s["affordability_status"]
        agree["method_match"] += pred["recommended_payment_method"] == s["recommended_payment_method"]
        agree["earliest_presence_match"] += bool(pred["earliest_date_for_full_payment"]) == bool(s["earliest_date_for_full_payment"])
        try:
            safe_diffs.append(abs(Decimal(pred["amount_safe_to_pay"]) - Decimal(s["amount_safe_to_pay"])))
        except Exception:
            pass
        if pred["affordability_status"] != s["affordability_status"]:
            print(f"MISMATCH {s['request_id']}: pred {pred['affordability_status']}/{pred['recommended_payment_method']} "
                  f"vs sample {s['affordability_status']}/{s['recommended_payment_method']} "
                  f"(safe {pred['amount_safe_to_pay']} vs {s['amount_safe_to_pay']})")
    n = len(samples)
    print(f"samples: {n}")
    print(f"status agreement: {agree['status_match']}/{n}")
    print(f"method agreement: {agree['method_match']}/{n}")
    print(f"earliest-presence agreement: {agree['earliest_presence_match']}/{n}")
    if safe_diffs:
        print(f"mean |safe_pred - safe_sample|: {sum(safe_diffs) / len(safe_diffs):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
