"""Buy or Wait? -- pipeline entry point (Agents 1+2+3).

Usage:
    python3 code/main.py [--requests dataset/requests.csv --out output.csv]

Reads only from dataset/, writes predictions to output.csv in the repo root,
then runs validation (PART B) and packaging (PART C: usage report + code.zip).

Deterministic: same inputs always produce the same outputs (sorted I/O,
Decimal money, no randomness). Secrets from environment variables only
(none required for the default fully-local run).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

import decide
import llm_tracker
import validate as validator
from forecast.engine import forecast_one
from state_builder import (build_all_states, build_fx_index, load_events,
                           load_messages, load_ocr_cache, load_rates)


def parse_args():
    ap = argparse.ArgumentParser(description="Buy or Wait? financial agent")
    ap.add_argument("--requests", default=str(REPO_ROOT / "dataset" / "requests.csv"))
    ap.add_argument("--out", default=str(REPO_ROOT / "output.csv"))
    ap.add_argument("--skip-package", action="store_true",
                    help="skip usage_report.md + code.zip packaging")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    llm_tracker.reset()

    with open(args.requests, newline="", encoding="utf-8") as fh:
        requests = list(csv.DictReader(fh))  # file order = output order
    with open(REPO_ROOT / "dataset" / "request_payment_options.csv",
              newline="", encoding="utf-8") as fh:
        options = list(csv.DictReader(fh))
    opts_by_req = defaultdict(list)
    for o in options:
        opts_by_req[o["request_id"]].append(o)

    user_ids = sorted({r["user_id"] for r in requests})
    print(f"building Agent-1 states for {len(user_ids)} users ...", flush=True)
    states = build_all_states(user_ids)
    ctx = {"all_events": load_events(), "messages": load_messages(),
           "fx_idx": build_fx_index(load_rates()), "ocr": load_ocr_cache()}
    print(f"states ready; forecasting + deciding {len(requests)} requests ...", flush=True)

    rows, counts = [], defaultdict(int)
    for req in requests:
        st = states.get(req["user_id"])
        if st is None:
            rows.append({"request_id": req["request_id"], "amount_safe_to_pay": "0",
                         "affordability_status": "not_affordable",
                         "recommended_payment_method": "not_recommended",
                         "payment_plan": "none",
                         "earliest_date_for_full_payment": "",
                         "spending_changes_needed": "none",
                         "decision_explanation": "No financial profile available; cannot recommend payment."})
            continue
        fr = forecast_one(req, st, ctx)
        row = decide.decide_request(st, req, fr, opts_by_req.get(req["request_id"], []))
        rows.append(row)
        counts[row["affordability_status"]] += 1

    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=validator.EXPECTED_COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {args.out} {dict(counts)}")

    code = validator.main(args.out)
    if code != 0:
        print("validation FAILED -- see code/validation_report.txt")
        return code
    if not args.skip_package:
        import package
        package.write_usage_report()
        package.build_code_zip()
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
