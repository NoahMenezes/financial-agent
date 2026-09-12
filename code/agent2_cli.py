"""Agent 2 CLI: run deterministic 90-day forecast for every request.

Reads dataset/requests.csv, builds clean states via Agent 1's state_builder
(shared cached load = one disk read), runs forecast_one per request, writes:
  - agent2_results.json (full numbers for Agent 3)
  - agent2_preview.csv (human-readable spot-check)

Stdlib only. No LLM/API calls. Deterministic: sorted requests, Decimal math.

Usage:
  python3 code/agent2_cli.py [--out-dir code] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DATASET = REPO_ROOT / "dataset"
sys.path.insert(0, str(HERE))

from forecast.engine import forecast_one  # noqa: E402
from state_builder import (  # noqa: E402
    build_all_states,
    build_fx_index,
    load_events,
    load_messages,
    load_ocr_cache,
    load_rates,
)


def fmt_money(v: Decimal, currency: str) -> str:
    q = v.quantize(Decimal("0.01"))
    if currency in ("IDR", "INR", "ZAR") and q == q.to_integral_value():
        return str(int(q))
    # Match sample style: keep 2dp but strip needless trailing zero to 1dp
    # (e.g. 603.30 -> 603.3) while keeping x.x0 -> x.x.
    s = format(q, ".2f")
    if s.endswith("0") and not s.endswith("00"):
        return s[:-1]
    if s.endswith("00"):
        # For EUR/USD keep .00? samples keep 620.40, so keep 2dp when even.
        # For zero-decimal currencies handled above; here keep 2dp.
        return s
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent 2 deterministic forecast")
    ap.add_argument("--out-dir", default=str(HERE), help="where to write results")
    ap.add_argument("--limit", type=int, default=0, help="process first N requests (0=all)")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(DATASET / "requests.csv", newline="", encoding="utf-8") as f:
        requests = list(csv.DictReader(f))  # keep file order (request_26..275)
    if args.limit:
        requests = requests[: args.limit]

    user_ids = sorted({r["user_id"] for r in requests})
    print(f"Building Agent-1 states for {len(user_ids)} users ...", flush=True)
    states = build_all_states(user_ids)
    # Shared raw inputs for recurring-salary projection (one disk read).
    ctx = {
        "all_events": load_events(),
        "messages": load_messages(),
        "fx_idx": build_fx_index(load_rates()),
        "ocr": load_ocr_cache(),
    }

    results: list[dict] = []
    preview_rows: list[dict] = []
    for r in requests:
        st = states[r["user_id"]]
        fr = forecast_one(r, st, ctx)
        results.append(fr.to_json_dict())
        preview_rows.append({
            "request_id": fr.request_id,
            "user_id": fr.user_id,
            "request_date": fr.request_date.isoformat(),
            "requested_amount": fmt_money(fr.requested_amount, fr.home_currency),
            "amount_safe_to_pay": fmt_money(fr.amount_safe_to_pay, fr.home_currency),
            "earliest_date_for_full_payment": (
                fr.earliest_date_for_full_payment.isoformat()
                if fr.earliest_date_for_full_payment else ""
            ),
            "safe_with_changes": fmt_money(fr.safe_with_changes, fr.home_currency),
            "earliest_with_changes": (
                fr.earliest_with_changes.isoformat() if fr.earliest_with_changes else ""
            ),
            "spending_candidates": "|".join(fr.spending_candidates) or "none",
        })

    with open(out_dir / "agent2_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1, sort_keys=False)
    with open(out_dir / "agent2_preview.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(preview_rows[0].keys()))
        w.writeheader()
        w.writerows(preview_rows)
    print(f"Wrote {len(results)} forecasts -> {out_dir/'agent2_results.json'}", flush=True)

    # Bounds self-check.
    bad = 0
    for fr, row in zip(results, requests):
        req = Decimal(str(row["requested_amount"]))
        safe = Decimal(str(fr["amount_safe_to_pay"]))
        if not (Decimal("0") <= safe <= req):
            print(f"BOUNDS FAIL {fr['request_id']}: safe={safe} req={req}")
            bad += 1
    print(f"bounds check: {len(results)-bad}/{len(results)} ok")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
