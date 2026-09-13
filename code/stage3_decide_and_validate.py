"""Stage 3 -- Decision, validation & packaging. 100% deterministic Python.

Reads code/state/forecasts.json + code/state/user_financial_states.json +
dataset/request_payment_options.csv + dataset/requests.csv, writes:
  output.csv (repo root) and evaluation/usage_report.md (sibling of code/).

Decision rules: eligibility gates, LOCKED whole-months installment duration
(common.months_span on the matched option's real dates), 6-step ranking,
status mapping, spending/plan formats, grounded templated explanations.
Validation reuses validate.py; packaging builds code.zip as code/ + sibling
evaluation/ (never nested). No LLM reasoning here; explanations are templated.
"""
from __future__ import annotations

import csv
import json
import sys
import zipfile
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))

from common import (  # noqa: E402
    EVAL_DIR, FORECASTS_JSON, OUTPUT_CSV, REPO_ROOT,
    STATES_JSON, STATE_DIR, installment_last_date, load_options,
    load_requests, months_span, parse_date,
)
import usage_tracker  # noqa: E402
import decide as decide_engine  # noqa: E402
import validate as validator  # noqa: E402


def _patch_months_rule() -> None:
    """Enforce LOCKED clarification #1 inside the decide engine (whole months)."""

    def whole_months_needed(first: date, n: int, freq_days: int) -> int:
        if n <= 1 or not freq_days:
            return 0
        last = installment_last_date(first, n, freq_days)
        return months_span(first, last)

    decide_engine.months_needed_option = whole_months_needed  # type: ignore


def _record_to_forecast(rec: dict):
    if "error" in rec:
        return None
    def _d(s: str):
        return parse_date(s)
    def _D(s: str):
        return Decimal(str(s))
    return SimpleNamespace(
        request_id=rec["request_id"], user_id=rec["user_id"],
        request_date=_d(rec["request_date"]), requested_amount=_D(rec["requested_amount"]),
        home_currency=rec.get("home_currency", ""),
        amount_safe_to_pay=_D(rec["amount_safe_to_pay"]),
        earliest_date_for_full_payment=_d(rec["earliest_date_for_full_payment"]) if rec.get("earliest_date_for_full_payment") else None,
        safe_with_changes=_D(rec.get("safe_with_changes", rec["amount_safe_to_pay"])),
        earliest_with_changes=_d(rec["earliest_with_changes"]) if rec.get("earliest_with_changes") else None,
        spending_candidates=list(rec.get("spending_candidates", [])),
        daily_dates=[_d(s) for s in rec.get("daily_dates", [])],
        daily_base=[_D(s) for s in rec.get("daily_base", [])],
        daily_base2=[_D(s) for s in rec.get("daily_base2", rec.get("daily_base", []))],
    )


def decide_all() -> list[dict]:
    _patch_months_rule()
    with open(STATES_JSON, encoding="utf-8") as fh:
        states = json.load(fh)
    with open(FORECASTS_JSON, encoding="utf-8") as fh:
        forecasts = json.load(fh)
    requests = load_requests()
    options = load_options()
    opts_by_req: dict = defaultdict(list)
    for o in options:
        opts_by_req[o["request_id"]].append(o)
    rows: list[dict] = []
    for req in requests:
        st = states.get(req["user_id"])
        rec = forecasts.get(req["request_id"])
        if st is None or rec is None or "error" in rec:
            rows.append({"request_id": req["request_id"], "amount_safe_to_pay": "0",
                         "affordability_status": "not_affordable",
                         "recommended_payment_method": "not_recommended",
                         "payment_plan": "none", "earliest_date_for_full_payment": "",
                         "spending_changes_needed": "none",
                         "decision_explanation": "No financial profile available; cannot recommend payment."})
            continue
        fr = _record_to_forecast(rec)
        row = decide_engine.decide_request(st, req, fr, opts_by_req.get(req["request_id"], []))
        rows.append(row)
    return rows


def write_output(rows: list[dict], out_path: Path | None = None) -> Path:
    out = out_path or OUTPUT_CSV
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=validator.EXPECTED_COLS,
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return out


def build_code_zip(zip_name: str = "code.zip") -> Path:
    """Required layout: code.zip -> code/... + evaluation/usage_report.md (sibling)."""
    out = REPO_ROOT / zip_name
    if out.exists():
        out.unlink()
    exclude_dirs = {".venv", "venv", "__pycache__", "node_modules", ".git",
                    ".pytest_cache", "build", "dist", "evaluation", "state"}
    # state/*.json are runtime-generated; ship image_cache only via migration source.
    # Keep ocr_cache.json (curated input) but NOT generated state/ JSONs or previews.
    # Legacy modules superseded by the staged pipeline (never imported by it)
    # are also excluded so the submission package contains only live code.
    exclude_files = {".env", "code.zip", "agent2_cli.py", "agent2_results.json",
                     "agent2_preview.csv", "package.py", "llm_tracker.py",
                     "validation_report.txt", ".usage_log.jsonl"}
    exclude_ext = {".pyc", ".pyo"}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in __import__("os").walk(CODE_DIR):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for f in files:
                if f == "ocr_cache.json":
                    full = Path(root) / f
                    zf.write(full, str(full.relative_to(REPO_ROOT)))
                    continue
                if f in exclude_files or Path(f).suffix in exclude_ext:
                    continue
                full = Path(root) / f
                zf.write(full, str(full.relative_to(REPO_ROOT)))
        # Sibling evaluation/ mirror (required submission path).
        if EVAL_DIR.is_dir():
            for f in sorted(p.name for p in EVAL_DIR.iterdir() if p.is_file()):
                zf.write(EVAL_DIR / f, f"evaluation/{f}")
        if (CODE_DIR / "README.md").exists():
            zf.write(CODE_DIR / "README.md", "README.md")
    return out


def run(skip_package: bool = False) -> int:
    rows = decide_all()
    out = write_output(rows)
    print(f"stage3: wrote {len(rows)} rows -> {out}")
    code = validator.main(str(out))
    if code != 0:
        print("stage3: validation FAILED")
        return code
    if not skip_package:
        rep = usage_tracker.build_usage_report()
        zp = build_code_zip()
        print(f"stage3: usage report -> {rep}")
        print(f"stage3: package {zp} ({zp.stat().st_size} bytes)")
        with zipfile.ZipFile(zp) as zf:
            names = zf.namelist()
        print(f"stage3: {len(names)} files; has evaluation/usage_report.md: "
              f"{'evaluation/usage_report.md' in names}; "
              f"nested code/evaluation present: {any(n.startswith('code/evaluation') for n in names)}")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
