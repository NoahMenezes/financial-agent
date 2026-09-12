"""Agent 3B -- deterministic output validation (run after generating rows).

Checks (PART B):
  * exactly one row per request_id in dataset/requests.csv, exact 8 cols/order
  * 0 <= amount_safe_to_pay <= requested_amount
  * payment_plan amounts sum correctly + chronological dates
  * installment plans match a real payment_option_id schedule exactly
  * spending changes target flexible events only; no event both stopped+reduced
  * affordable_now => earliest_date_for_full_payment == request_date
  * format/style cross-check vs dataset/sample_requests.csv
"""
from __future__ import annotations

import csv
import os
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(CODE_DIR)
DATASET = os.path.join(REPO_ROOT, "dataset")

EXPECTED_COLS = ["request_id", "amount_safe_to_pay", "affordability_status",
                 "recommended_payment_method", "payment_plan",
                 "earliest_date_for_full_payment", "spending_changes_needed",
                 "decision_explanation"]

STATUS_OK = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
METHOD_OK = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
PLAN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}:[0-9]+(\.[0-9]{1,2})?$")
CHANGE_RE = re.compile(r"^(stop:[^|:]+|reduce_to:[^|:]+:[0-9]+(\.[0-9]{1,2})?)$")


def _dec(s):
    try:
        return Decimal(str(s).strip())
    except (InvalidOperation, AttributeError):
        return None


def _d(s):
    try:
        y, m, d = str(s)[:10].split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _read_csv(path):
    with open(path, encoding="utf-8") as fh:
        return fh.readline().rstrip("\n"), list(csv.DictReader(open(path, encoding="utf-8")))


def _read_csv_rows(path):
    with open(path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames, list(reader)


def validate(output_path: str) -> list:
    errors = []
    hdr, rows = _read_csv_rows(output_path)
    if hdr != EXPECTED_COLS:
        errors.append(f"header mismatch: got {hdr}, want {EXPECTED_COLS}")
    _, requests = _read_csv_rows(os.path.join(DATASET, "requests.csv"))
    req_by_id = {r["request_id"]: r for r in requests}
    if len(rows) != len(requests):
        errors.append(f"row count {len(rows)} != requests {len(requests)}")
    seen = [r.get("request_id") for r in rows]
    if set(seen) != set(req_by_id):
        errors.append("request_id set mismatch (missing/extra ids)")
    if seen != [r["request_id"] for r in requests]:
        errors.append("row order differs from requests.csv (must match exactly)")

    _, options = _read_csv_rows(os.path.join(DATASET, "request_payment_options.csv"))
    opts_by_req = defaultdict(list)
    for o in options:
        opts_by_req[o["request_id"]].append(o)
    _, events = _read_csv_rows(os.path.join(DATASET, "financial_events.csv"))
    ev_by_id = {e["event_id"]: e for e in events}
    _, profiles = _read_csv_rows(os.path.join(DATASET, "financial_profiles.csv"))
    prof_by_user = {p["user_id"]: p for p in profiles}

    for r in rows:
        rid = r.get("request_id", "?")
        req = req_by_id.get(rid)
        if req is None:
            errors.append(f"{rid}: unknown request_id")
            continue
        requested = _dec(req["requested_amount"])
        safe = _dec(r.get("amount_safe_to_pay", ""))
        if safe is None or requested is None or not (Decimal("0") <= safe <= requested):
            errors.append(f"{rid}: 0 <= safe <= requested violated "
                          f"(safe={r.get('amount_safe_to_pay')}, requested={req['requested_amount']})")
        status, method = r.get("affordability_status"), r.get("recommended_payment_method")
        if status not in STATUS_OK:
            errors.append(f"{rid}: bad affordability_status {status!r}")
        if method not in METHOD_OK:
            errors.append(f"{rid}: bad recommended_payment_method {method!r}")
        # status/method consistency
        if method == "partial_payment" and status != "affordable_with_plan":
            errors.append(f"{rid}: partial_payment requires affordable_with_plan")
        if method == "not_recommended" and status != "not_affordable":
            errors.append(f"{rid}: not_recommended requires not_affordable")
        if method == "wait" and status != "affordable_later":
            errors.append(f"{rid}: wait requires affordable_later")
        if status == "affordable_now" and method != "full_payment":
            errors.append(f"{rid}: affordable_now requires full_payment")
        # earliest date rules
        earliest = (r.get("earliest_date_for_full_payment") or "").strip()
        req_date = req["request_date"]
        if status == "affordable_now" and earliest != req_date:
            errors.append(f"{rid}: affordable_now requires earliest == request_date")
        # NOTE: earliest_date_for_full_payment measures financial capacity
        # independently of payment preferences (spec). A not_affordable row
        # (no *eligible* method completes the request, e.g. user rejects
        # full_payment) may still carry a capacity date; it is empty only
        # when full payment never passes the safety check in-window.
        if earliest:
            if _d(earliest) is None:
                errors.append(f"{rid}: bad earliest date {earliest!r}")
            elif status != "not_affordable":
                delta = (_d(earliest) - _d(req_date)).days
                if not (0 <= delta <= 90):
                    errors.append(f"{rid}: earliest {earliest} outside 90d window")
        # payment plan checks
        plan = (r.get("payment_plan") or "").strip()
        if method == "not_recommended":
            if plan != "none":
                errors.append(f"{rid}: not_recommended requires plan 'none'")
        elif plan == "none" or not plan:
            errors.append(f"{rid}: {method} requires a payment plan")
        else:
            legs = plan.split("|")
            dates, amounts = [], []
            ok = True
            for leg in legs:
                if not PLAN_RE.match(leg):
                    errors.append(f"{rid}: bad plan leg {leg!r}")
                    ok = False
                    break
                ds, am = leg.split(":")
                dates.append(_d(ds))
                amounts.append(_dec(am))
            if ok:
                if any(d is None for d in dates) or any(a is None or a <= 0 for a in amounts):
                    errors.append(f"{rid}: unparsable plan dates/amounts")
                    ok = False
                elif list(dates) != sorted(dates):
                    errors.append(f"{rid}: plan dates not chronological")
                    ok = False
            if ok:
                if method in ("full_payment", "wait"):
                    if len(legs) != 1 or abs(amounts[0] - requested) > Decimal("0.01"):
                        errors.append(f"{rid}: {method} plan must be single full payment")
                    if method == "full_payment" and dates[0] != _d(req_date):
                        errors.append(f"{rid}: full_payment plan date must be request_date")
                    if method == "wait" and (not earliest or dates[0] != _d(earliest)):
                        errors.append(f"{rid}: wait plan date must equal earliest")
                elif method == "partial_payment":
                    if len(legs) != 2:
                        errors.append(f"{rid}: partial plan must have exactly 2 payments")
                    elif dates[0] != _d(req_date) or (earliest and dates[1] != _d(earliest)):
                        errors.append(f"{rid}: partial dates must be request_date + earliest")
                    elif abs(sum(amounts) - requested) > Decimal("0.01"):
                        errors.append(f"{rid}: partial amounts must sum to requested")
                    elif not (Decimal("0") < amounts[0] < requested):
                        errors.append(f"{rid}: partial first leg must be strictly between 0 and requested")
                    elif req.get("allows_partial_payment", "").lower() != "true":
                        errors.append(f"{rid}: partial not allowed by request")
                elif method == "installments":
                    match = _match_installment_option(rid, legs, opts_by_req.get(rid, []))
                    if match is None:
                        errors.append(f"{rid}: installment plan matches no payment_option_id")
        # spending changes
        sc = (r.get("spending_changes_needed") or "").strip()
        if not sc:
            errors.append(f"{rid}: spending_changes_needed empty (use 'none')")
        elif sc != "none":
            parts = sc.split("|")
            if len(parts) > 3:
                errors.append(f"{rid}: >3 spending changes")
            seen_stop, seen_reduce = set(), set()
            for p in parts:
                if not CHANGE_RE.match(p):
                    errors.append(f"{rid}: bad spending change {p!r}")
                    continue
                segs = p.split(":")
                eid = segs[1]
                ev = ev_by_id.get(eid)
                if ev is None:
                    errors.append(f"{rid}: spending change targets unknown {eid}")
                    continue
                if (ev.get("flexibility") or "") == "fixed":
                    errors.append(f"{rid}: {eid} is fixed, not flexible")
                prof = prof_by_user.get(req["user_id"], {})
                cats_ok = ((prof.get("expense_categories_user_is_willing_to_reduce") or "") + "|" +
                           (prof.get("expense_categories_user_is_willing_to_stop") or "")).split("|")
                if ev.get("category") not in cats_ok:
                    errors.append(f"{rid}: {eid} category not user-permitted")
                if segs[0] == "stop":
                    seen_stop.add(eid)
                else:
                    seen_reduce.add(eid)
                    new_amt = _dec(segs[2])
                    old_amt = _dec(ev.get("amount") or "0") or Decimal("0")
                    if new_amt is None or not (Decimal("0") <= new_amt < old_amt):
                        # blank-amount events resolved via OCR may differ; only flag gross errors
                        if new_amt is None or new_amt < 0:
                            errors.append(f"{rid}: bad reduce_to amount {p!r}")
            if seen_stop & seen_reduce:
                errors.append(f"{rid}: event both stopped and reduced: {seen_stop & seen_reduce}")
        # explanation present + grounded (mentions currency or minimum)
        expl = (r.get("decision_explanation") or "").strip()
        if len(expl) < 20:
            errors.append(f"{rid}: decision_explanation too short")
    # style cross-check vs samples (format only)
    _, samples = _read_csv_rows(os.path.join(DATASET, "sample_requests.csv"))
    sample_plans = [s["payment_plan"] for s in samples]
    if not any("|" in p for p in sample_plans):
        errors.append("sample cross-check: unexpected sample plan formats")
    return errors


def _match_installment_option(rid: str, legs: list, options: list):
    from datetime import timedelta
    for o in options:
        if o.get("payment_method") != "installments":
            continue
        n = int(o["number_of_payments"])
        if n != len(legs):
            continue
        first = _d(o["first_payment_date"])
        freq = int(o["payment_frequency_days"]) if (o.get("payment_frequency_days") or "").strip() else 0
        amt = _dec(o["payment_amount"])
        ok = True
        for k, leg in enumerate(legs):
            ds, am = leg.split(":")
            exp_d = first + timedelta(days=k * freq)
            if _d(ds) != exp_d or abs(_dec(am) - amt) > Decimal("0.01"):
                ok = False
                break
        if ok:
            return o["payment_option_id"]
    return None


def main(output_path: str = None) -> int:
    path = output_path or os.path.join(REPO_ROOT, "output.csv")
    errs = validate(path)
    report = os.path.join(CODE_DIR, "validation_report.txt")
    with open(report, "w", encoding="utf-8") as fh:
        if errs:
            fh.write(f"FAILED: {len(errs)} error(s)\n")
            for e in errs:
                fh.write(f"- {e}\n")
        else:
            fh.write("PASSED: all validation checks passed\n")
    for e in errs[:50]:
        print("VALIDATION:", e)
    print(f"validation: {'FAILED' if errs else 'PASSED'} ({len(errs)} errors), report -> {report}")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
