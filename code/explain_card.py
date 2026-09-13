"""Decision Cards + Provenance (differentiator, read-only).

Builds human-readable audit cards from existing pipeline files WITHOUT
recomputing decisions, so output.csv stays byte-identical.

Reads:
  code/state/user_financial_states.json
  code/state/forecasts.json
  dataset/requests.csv + request_payment_options.csv
  output.csv (repo root, final verdicts)

Writes:
  code/state/decision_cards.json (full 250, gitignored runtime cache)
  evaluation/decision_cards.md (demo: summary + first N cards, SHIPPED in code.zip)

Usage:
  code/.venv/bin/python code/explain_card.py [--limit 10]
  code/.venv/bin/python code/explain_card.py --all  # full json + full md

Deterministic: sorted I/O, no LLM, no randomness.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))
REPO_ROOT = CODE_DIR.parent

try:
    from common import EVAL_DIR, STATE_DIR
except ImportError:
    from code.common import EVAL_DIR, STATE_DIR  # type: ignore


def _load_json(p: Path) -> dict:
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _load_csv(p: Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _money(x, cur: str) -> str:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return f"{cur} {x}"
    if cur in ("IDR", "INR", "ZAR") and float(f).is_integer():
        return f"{cur} {int(f):,}"
    return f"{cur} {f:,.2f}"


def build_card(req: dict, st: dict, fc: dict, out_row: dict,
               options: list[dict]) -> dict:
    """Pure formatting: no math, only collates already-computed values."""
    home = st.get("home_currency", "")
    cushion = float(st.get("current_balance", 0)) - float(st.get("minimum_balance_to_keep", 0))
    recur = st.get("recurring_expenses", [])
    recur_mo = sum(float(r.get("forecast_amount", 0)) for r in recur)
    pend = st.get("pending_scheduled_debits", [])
    pend_tot = sum(float(d.get("amount_home", 0)) for d in pend)
    inc = st.get("confirmed_future_income", [])
    # Eligibility narrative (mirrors decide.py gates, explains runner-ups).
    methods = set(st.get("payment_methods_user_will_consider") or [])
    allows_partial = str(req.get("allows_partial_payment", "")).lower() == "true"
    max_m = (st.get("max_installment_months") or "").strip() or "no-installments"
    elig_notes: list[str] = []
    if "full_payment" not in methods:
        elig_notes.append("full_payment not in user-accepted methods")
    if not allows_partial:
        elig_notes.append("partial_payment blocked: request allows_partial=false")
    elif "partial_payment" not in methods:
        elig_notes.append("partial_payment not in user-accepted methods")
    if "installments" not in methods:
        elig_notes.append("installments not in user-accepted methods")
    elif max_m == "no-installments":
        elig_notes.append("installments blocked: max_installment_months blank")
    else:
        n_inst = sum(1 for o in options if o.get("payment_method") == "installments")
        elig_notes.append(f"installments: {n_inst} option(s), max {max_m} whole-months")
    # Evidence ledger.
    fx_fallbacks = [
        f"{eid}:{p.get('fx_fallback', '')}"
        for eid, p in (st.get("provenance") or {}).items()
        if isinstance(p, dict) and "fx_fallback" in p
    ][:5]
    card = {
        "request_id": req["request_id"],
        "user_id": req["user_id"],
        "verdict": {
            "status": out_row.get("affordability_status"),
            "method": out_row.get("recommended_payment_method"),
            "plan": out_row.get("payment_plan"),
            "earliest": out_row.get("earliest_date_for_full_payment") or "none-in-90d",
            "spending": out_row.get("spending_changes_needed"),
        },
        "money": {
            "requested": _money(req.get("requested_amount"), home),
            "safe_today": _money(out_row.get("amount_safe_to_pay"), home),
            "balance": _money(st.get("current_balance"), home),
            "minimum": _money(st.get("minimum_balance_to_keep"), home),
            "cushion": _money(round(cushion, 2), home),
            "recurring_monthly_est": _money(round(recur_mo, 2), home),
            "pending_debits_reserved": _money(round(pend_tot, 2), home),
            "confirmed_income_rows": len(inc),
        },
        "evidence": {
            "recurring_series": len(recur),
            "amendments": len(st.get("amendments", [])),
            "quarantined_instructions": len(st.get("quarantine", [])),
            "ocr_amounts_used": len(st.get("ocr_applied", [])),
            "fx_fallbacks_shown": fx_fallbacks,
            "forecast_safe": fc.get("amount_safe_to_pay") if fc else "?",
            "forecast_earliest": fc.get("earliest_date_for_full_payment") or "none" if fc else "?",
        },
        "why_not_others": elig_notes,
        "explanation": out_row.get("decision_explanation"),
    }
    return card


def card_to_md(c: dict) -> str:
    v, m = c["verdict"], c["money"]
    lines = [
        f"### {c['request_id']} ({c['user_id']}) — {v['status']} via {v['method']}",
        f"- Requested {m['requested']}, safe today {m['safe_today']}, earliest full: {v['earliest']}",
        f"- Balance {m['balance']} (min {m['minimum']}, cushion {m['cushion']})",
        f"- Recurring ~{m['recurring_monthly_est']}/mo x{c['evidence']['recurring_series']}, "
        f"pending reserved {m['pending_debits_reserved']}, confirmed income rows {m['confirmed_income_rows']}",
        f"- Plan: `{v['plan']}` | Spending: `{v['spending']}`",
        f"- Evidence: {c['evidence']['amendments']} amendments, "
        f"{c['evidence']['quarantined_instructions']} quarantined, "
        f"{c['evidence']['ocr_amounts_used']} OCR amounts",
        f"- Gates: {'; '.join(c['why_not_others']) or 'all methods eligible'}",
        f"> {c['explanation']}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build decision audit cards (read-only)")
    ap.add_argument("--limit", type=int, default=10, help="demo cards in md")
    ap.add_argument("--all", action="store_true", help="also write full md (250)")
    args = ap.parse_args()

    states = _load_json(STATE_DIR / "user_financial_states.json")
    forecasts = _load_json(STATE_DIR / "forecasts.json")
    requests = _load_csv(REPO_ROOT / "dataset" / "requests.csv")
    options = _load_csv(REPO_ROOT / "dataset" / "request_payment_options.csv")
    out_rows = {r["request_id"]: r for r in _load_csv(REPO_ROOT / "output.csv")}
    opts_by_req: dict[str, list[dict]] = {}
    for o in options:
        opts_by_req.setdefault(o["request_id"], []).append(o)

    cards: list[dict] = []
    for req in requests:  # file order = requests.csv order
        st = states.get(req["user_id"], {})
        fc = forecasts.get(req["request_id"], {})
        row = out_rows.get(req["request_id"], {})
        cards.append(build_card(req, st, fc, row, opts_by_req.get(req["request_id"], [])))

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / "decision_cards.json", "w", encoding="utf-8") as fh:
        json.dump({c["request_id"]: c for c in cards}, fh, indent=1, sort_keys=True)

    status_c = Counter(c["verdict"]["status"] for c in cards)
    method_c = Counter(c["verdict"]["method"] for c in cards)
    show = cards if args.all else cards[: args.limit]
    md = [
        "# Decision Cards — audit sample (read-only, output.csv unchanged)",
        "",
        f"Cards: {len(cards)} (showing {len(show)}). "
        f"Status {dict(status_c)}. Method {dict(method_c)}.",
        "",
        "Each card collates balance/cushion, recurring + pending + income, "
        "message/image evidence counts, eligibility gates for runner-up methods, "
        "and the shipped explanation. Full JSON: `code/state/decision_cards.json` "
        "(runtime cache, not shipped).",
        "",
    ]
    for c in show:
        md.append(card_to_md(c))
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    out_md = EVAL_DIR / "decision_cards.md"
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"cards: {len(cards)} -> code/state/decision_cards.json + {out_md} ({len(show)} shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
