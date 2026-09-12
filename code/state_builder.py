"""Agent 1 — Financial State Builder for "Buy or Wait?".

Builds one clean JSON/dict per user_id with a provenance ledger.
Scope is STRICTLY Agent 1: data cleaning / state reconstruction only.
No forecasting, no decisions, no output.csv logic (Agents 2/3 own those).

Covers the Agent-1 job steps:
 1. Load profiles + events (balance, minimum, priorities, prefs, max_installment_months;
    recurring/one-time, settled/pending/scheduled/failed/cancelled/unrealized).
 2. FX conversion to home_currency via exchange_rates.csv (settlement date + pair,
    exact -> most-recent-prior -> next-future fallback, all logged).
 3. Recurring vs one-time + essential vs flexible flags (flexible only may be
    stopped/reduced downstream).
 4. Blank amounts resolved from code/ocr_cache.json (built from
    dataset/media/images/<image_id>.png). Never zero.
 5. messages.csv + images amend/clarify/delay/cancel/confirm facts.
 6. UNTRUSTED-DATA firewall: facts only, embedded instructions quarantined.
 7. Conflict order: (a) explicit cancel/settle/amend > (b) newer same-source >
    (c) settled > estimate > (d) financially safer.
 8. Only CONFIRMED/SETTLED income counts. Pending credits/bonus/commission/refund/
    lottery/unrealized gains ignored until settled.
 9. De-dup via linked_event_id lifecycle + transfer-netting (link is a hint,
    cash-status decides).

Stdlib only. Deterministic: sorted I/O, no randomness, no network calls.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import median

# ---------------------------------------------------------------- paths ---

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DATASET = REPO_ROOT / "dataset"
MEDIA = DATASET / "media" / "images"
OCR_CACHE = HERE / "ocr_cache.json"

PROFILES_CSV = DATASET / "financial_profiles.csv"
EVENTS_CSV = DATASET / "financial_events.csv"
RATES_CSV = DATASET / "exchange_rates.csv"
MESSAGES_CSV = DATASET / "messages.csv"
IMAGES_CSV = DATASET / "images.csv"

# ------------------------------------------------------------- constants ---

CASH_STATUSES = {"settled", "pending", "scheduled"}
IGNORE_STATUSES = {"failed", "cancelled", "unrealized"}

# Pending/scheduled CREDITS that must NOT count until settled (spec: bonuses,
# commissions, refunds, lottery, investment gains, pending payouts).
PENDING_CREDIT_BLOCKLIST = (
    "bonus", "commission", "refund", "lottery", "prize", "payout",
    "invoice", "valuation", "gain", "pending",
)

INSTRUCTION_PATTERNS = (
    r"\bignore\s+(the\s+)?(rules|instructions|above)\b",
    r"\bdisregard\b",
    r"\boverride\b",
    r"\bapprove\s+this\b",
    r"\bdo\s+not\s+follow\b",
)


# --------------------------------------------------------------- helpers ---

def _parse_date(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    # event dates are YYYY-MM-DD; messages use ISO timestamps
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _f(s: str) -> float | None:
    s = (s or "").strip().replace(",", "")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _p90(values: list[float]) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    if len(vs) == 1:
        return vs[0]
    # nearest-rank p90, deterministic
    import math
    k = min(len(vs) - 1, max(0, math.ceil(0.9 * len(vs)) - 1))
    return vs[k]


def _split_list(s: str) -> list[str]:
    return [p.strip() for p in (s or "").split("|") if p.strip()]


# ------------------------------------------------------------------ load ---

def load_profiles() -> dict:
    with open(PROFILES_CSV, newline="", encoding="utf-8") as f:
        return {r["user_id"]: r for r in csv.DictReader(f)}


def load_events() -> list[dict]:
    with open(EVENTS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_rates() -> list[dict]:
    with open(RATES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_messages() -> list[dict]:
    with open(MESSAGES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_images_index() -> list[dict]:
    with open(IMAGES_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_ocr_cache() -> dict:
    """event_id -> {amount, currency, image_id, reasoning}."""
    with open(OCR_CACHE, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for row in data["images"]:
        out[row["event_id"]] = row
    return out


# -------------------------------------------------------------------- FX ---

def build_fx_index(rates: list[dict]) -> dict[tuple[str, str], list[tuple[date, float]]]:
    """(from, to) -> sorted [(rate_date, rate)]."""
    idx: dict = defaultdict(list)
    for r in rates:
        d = _parse_date(r["rate_date"])
        rate = _f(r["rate"])
        if d is None or rate is None:
            continue
        idx[(r["from_currency"].strip(), r["to_currency"].strip())].append((d, rate))
    for k in idx:
        idx[k].sort()
    return idx


def fx_convert(amount: float, from_cur: str, to_cur: str, settle: date | None,
               fx_idx: dict, prov: dict) -> tuple[float, str]:
    """Convert amount; returns (value, fx_note). Logs fallback in prov dict."""
    if from_cur == to_cur or amount is None:
        return amount, "fx:none:same_currency"
    key = (from_cur, to_cur)
    series = fx_idx.get(key, [])
    if not series:
        # No direct pair: try inverse pair (should not happen; dataset has
        # directed pairs only). Fall back to 1.0 and flag as safer-review.
        prov["fx_fallback"] = f"no_pair:{from_cur}->{to_cur}:rate=1.0:REVIEW"
        return amount, "fx:missing_pair:1.0"
    if settle is None:
        d, r = series[-1]
        prov["fx_fallback"] = f"no_settle_date:used_latest:{d}:{r}"
        return amount * r, f"fx:latest:{d}:{r}"
    # exact match?
    for d, r in series:
        if d == settle:
            return amount * r, f"fx:exact:{d}:{r}"
    # most recent prior
    prior = [(d, r) for d, r in series if d <= settle]
    if prior:
        d, r = prior[-1]
        prov["fx_fallback"] = f"gap:used_prior:{d}:for_settle:{settle}:{r}"
        return amount * r, f"fx:prior:{d}:{r}"
    d, r = series[0]
    prov["fx_fallback"] = f"gap:used_next:{d}:for_settle:{settle}:{r}"
    return amount * r, f"fx:next:{d}:{r}"


# ----------------------------------------------- untrusted-data firewall ---

def classify_text(text: str) -> str:
    """FACT vs INSTRUCTION vs NOISE. Instructions are quarantined, never obeyed."""
    t = text or ""
    for pat in INSTRUCTION_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return "INSTRUCTION"
    # facts carry amounts, dates, or lifecycle verbs
    if re.search(r"\d", t) or re.search(
        r"cancel|settlement|settled|amend|replac|revis|updated|confirm|received|"
        r"refund|salary|gaji|invoice|faktur|rent|bonus|commission|prize|payout|"
        r"transfer|paid|payable|due|approved|pending|failed|closed",
        t, re.IGNORECASE,
    ):
        return "FACT"
    return "NOISE"


AMOUNT_RE = re.compile(
    r"(?:IDR|INR|ZAR|USD|EUR)?\s*\$?\s*(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def extract_facts(text: str) -> dict:
    """Pull factual nuggets only: amounts, dates, lifecycle signals."""
    t = text or ""
    amounts = []
    for m in AMOUNT_RE.finditer(t):
        v = _f(m.group(1))
        if v is not None and v > 0:
            amounts.append(v)
    dates = DATE_RE.findall(t)
    low = t.lower()
    signals = {
        "cancel": any(k in low for k in ("cancel", "closed", "will not", "ended", "no off-season")),
        "settled": any(k in low for k in ("settled", "received", "reached your account", "paid in",
                                          "payment was received", "claim is now closed")),
        "pending_only": any(k in low for k in ("not reached", "not been credited", "still pending",
                                               "still in payment processing", "awaiting approval",
                                               "until the payout", "has not reached")),
        "amend": any(k in low for k in ("replac", "revis", "updated", "amend", "new amount",
                                        "increases", "reduced", "changed")),
        "refund": "refund" in low,
        "transfer_pair": "transfer between your two accounts" in low,
    }
    return {"amounts": amounts, "dates": dates, "signals": signals}


# ------------------------------------------------- message-derived rules ---

def parse_message_rules(msg: dict) -> list[dict]:
    """Deterministic rule extraction from one message. Returns amendment dicts."""
    text = msg.get("message_text", "")
    facts = extract_facts(text)
    out: list[dict] = []
    low = text.lower()
    sent = (msg.get("sent_at", "") or "")[:10]

    # Salary / payroll confirmations & changes (EN + ID).
    if msg.get("source_type") == "employer" or "salar" in low or "gaji" in low or "payroll" in low:
        out.append({
            "kind": "payroll_note", "source": msg["message_id"],
            "related_event_id": msg.get("related_event_id") or None,
            "request_id": msg.get("request_id") or None,
            "facts": facts, "text_hint": text[:160],
        })
    # Approved invoices (countable on settlement date) vs awaiting-approval (ignore).
    if "invoice" in low or "faktur" in low:
        if facts["signals"]["pending_only"] or "awaiting approval" in low or "masih menunggu" in low:
            out.append({"kind": "invoice_pending_ignore", "source": msg["message_id"],
                        "related_event_id": msg.get("related_event_id") or None,
                        "facts": facts, "text_hint": text[:160]})
        elif "approved" in low or "disetujui" in low or "confirmed" in low:
            out.append({"kind": "invoice_approved", "source": msg["message_id"],
                        "related_event_id": msg.get("related_event_id") or None,
                        "facts": facts, "text_hint": text[:160]})
    # Refunds initiated-but-not-credited -> do NOT count yet.
    if facts["signals"]["refund"] and facts["signals"]["pending_only"]:
        out.append({"kind": "refund_pending_ignore", "source": msg["message_id"],
                    "related_event_id": msg.get("related_event_id") or None,
                    "facts": facts, "text_hint": text[:160]})
    # Internal transfer pairs -> net to zero downstream.
    if facts["signals"]["transfer_pair"]:
        out.append({"kind": "internal_transfer_pair", "source": msg["message_id"],
                    "related_event_id": msg.get("related_event_id") or None,
                    "facts": facts, "text_hint": text[:160]})
    # Prize/lottery/investment pending -> ignore until settled.
    if any(k in low for k in ("prize", "lottery", "market value", "no units have been sold")):
        if facts["signals"]["pending_only"] or "no cash proceeds" in low or "not been credited" in low:
            out.append({"kind": "windfall_pending_ignore", "source": msg["message_id"],
                        "related_event_id": msg.get("related_event_id") or None,
                        "facts": facts, "text_hint": text[:160]})
    # Service payouts still pending -> ignore.
    if "still pending" in low and ("payout" in low or "earnings" in low):
        out.append({"kind": "payout_pending_ignore", "source": msg["message_id"],
                    "related_event_id": msg.get("related_event_id") or None,
                    "facts": facts, "text_hint": text[:160]})
    # Explicit date replacement ("replaces the payroll date ... revised date").
    if "replac" in low or ("revis" in low and facts["dates"]):
        out.append({"kind": "date_replacement", "source": msg["message_id"],
                    "related_event_id": msg.get("related_event_id") or None,
                    "facts": facts, "sent": sent, "text_hint": text[:160]})
    # Rent increase (e.g. StayLedger +12%).
    m = re.search(r"increases?\s+monthly\s+rent\s+by\s+(\d+(?:\.\d+)?)\s*%", low)
    if m:
        out.append({"kind": "rent_increase_pct", "pct": float(m.group(1)),
                    "source": msg["message_id"], "facts": facts,
                    "text_hint": text[:160]})
    return out


# ------------------------------------------------------------ core build ---

def _is_countable_credit(ev: dict) -> bool:
    """Only confirmed/settled income counts. Everything speculative is out."""
    if ev["direction"] == "non_cash":
        return False
    if ev["direction"] != "credit":
        return False
    if ev["status"] != "settled":
        desc = f"{ev['description']} {ev['event_type']} {ev['category']}".lower()
        if any(k in desc for k in PENDING_CREDIT_BLOCKLIST):
            return False
        # scheduled salary WITH explicit confirmation note may still count at
        # Agent 2 stage on its settlement date; keep it flagged, not dropped.
        return ev["event_type"] == "income" and ev["status"] == "scheduled"
    desc = f"{ev['description']} {ev['event_type']}".lower()
    # settled windfalls that already landed DO count (they are cash now only
    # via opening balance; future scheduled ones do not).
    return True


def build_user_state(user_id: str, profiles: dict | None = None,
                     all_events: list[dict] | None = None,
                     fx_idx: dict | None = None,
                     ocr: dict | None = None,
                     messages: list[dict] | None = None) -> dict:
    """Build the clean Agent-1 state for one user (with provenance)."""
    profiles = profiles if profiles is not None else load_profiles()
    all_events = all_events if all_events is not None else load_events()
    fx_idx = fx_idx if fx_idx is not None else build_fx_index(load_rates())
    ocr = ocr if ocr is not None else load_ocr_cache()
    messages = messages if messages is not None else load_messages()

    if user_id not in profiles:
        raise KeyError(f"unknown user_id {user_id}")
    prof = profiles[user_id]
    home = prof["home_currency"].strip()
    minimum = float(prof["minimum_balance_to_keep"])
    balance = float(prof["current_available_balance"])
    protect = set(_split_list(prof.get("expense_categories_to_protect", "")))
    willing_reduce = set(_split_list(prof.get("expense_categories_user_is_willing_to_reduce", "")))
    willing_stop = set(_split_list(prof.get("expense_categories_user_is_willing_to_stop", "")))

    user_events = sorted(
        [dict(r) for r in all_events if r["user_id"] == user_id],
        key=lambda r: (r["event_date"], r["event_id"]),
    )

    # ---- blank amounts from OCR cache (never zero) ----
    ocr_applied: list[dict] = []
    for ev in user_events:
        if not (ev.get("amount") or "").strip():
            hit = ocr.get(ev["event_id"])
            if hit is None:
                raise ValueError(f"blank amount with no OCR entry: {ev['event_id']}")
            ev["amount"] = str(hit["extracted_amount"])
            # currency on the row stays as printed; conversion uses home below
            ocr_applied.append({"event_id": ev["event_id"], "image_id": hit["image_id"],
                                "amount": hit["extracted_amount"],
                                "currency": hit["currency"],
                                "reasoning": hit["reasoning"]})

    # ---- FX to home + per-event provenance ----
    provenance: dict[str, dict] = {}
    for ev in user_events:
        prov: dict = {"sources": ["financial_events.csv:" + ev["event_id"]],
                      "rule": "row_as_is"}
        raw = _f(ev["amount"])
        ev_cur = (ev.get("currency") or home).strip() or home
        settle = _parse_date(ev.get("settlement_date") or ev.get("event_date"))
        ev["_settle"] = settle
        ev["_raw_amount"] = raw
        val, note = fx_convert(raw, ev_cur, home, settle, fx_idx, prov)
        ev["amount_home"] = round(val, 2)
        ev["_fx_note"] = note
        if ev["event_id"] in ocr:
            prov["sources"].append("image:" + ocr[ev["event_id"]]["image_id"])
            prov["rule"] = "ocr_amount_from_image"
        provenance[ev["event_id"]] = prov

    # ---- messages: firewall + rules ----
    user_msgs = [m for m in messages if m["user_id"] == user_id]
    amendments: list[dict] = []
    quarantine: list[dict] = []
    msg_rules: list[dict] = []
    for m in user_msgs:
        cls = classify_text(m.get("message_text", ""))
        if cls == "INSTRUCTION":
            quarantine.append({"message_id": m["message_id"],
                               "reason": "embedded_instruction_quarantined",
                               "hint": (m.get("message_text", "") or "")[:120]})
            continue  # never obeyed, still logged
        for rule in parse_message_rules(m):
            rule["user_id"] = user_id
            msg_rules.append(rule)
        # direct-event confirmations / cancellations
        rel = (m.get("related_event_id") or "").strip()
        if rel and rel in provenance:
            facts = extract_facts(m.get("message_text", ""))
            if facts["signals"]["pending_only"]:
                amendments.append({"source": m["message_id"], "type": "confirm_pending_do_not_count",
                                   "event_id": rel, "resolution": "kept_status_pending_no_cash_effect",
                                   "reasoning": "explicit pending confirmation; rule (a)"})
                provenance[rel]["rule"] = "confirmed_pending_by_message:" + m["message_id"]
            elif facts["signals"]["settled"]:
                amendments.append({"source": m["message_id"], "type": "confirm_settled",
                                   "event_id": rel, "resolution": "confirmed_settled",
                                   "reasoning": "explicit settlement confirmation; rule (a)"})
                provenance[rel]["rule"] = "confirmed_settled_by_message:" + m["message_id"]

    # user-level amendments (rent hikes, payroll changes, approved invoices)
    rent_hike_pct: float | None = None
    for r in msg_rules:
        if r["kind"] == "rent_increase_pct":
            rent_hike_pct = r["pct"]
            amendments.append({"source": r["source"], "type": "rent_increase_pct",
                               "pct": r["pct"], "resolution": "future_rent_scaled",
                               "reasoning": "explicit amendment; rule (a)"})
        elif r["kind"] in ("invoice_pending_ignore", "refund_pending_ignore",
                           "windfall_pending_ignore", "payout_pending_ignore"):
            amendments.append({"source": r["source"], "type": r["kind"],
                               "event_id": r.get("related_event_id"),
                               "resolution": "excluded_from_cash_until_settled",
                               "reasoning": "pending-only confirmation; rule (a)"})
        elif r["kind"] == "invoice_approved":
            amendments.append({"source": r["source"], "type": "invoice_approved",
                               "resolution": "counted_on_settlement_date_if_scheduled",
                               "facts": r["facts"], "reasoning": "explicit approval; rule (a)"})
        elif r["kind"] == "date_replacement":
            amendments.append({"source": r["source"], "type": "date_replacement",
                               "facts": r["facts"], "resolution": "use_revised_date",
                               "reasoning": "explicit amendment supersedes earlier; rules (a)+(b)"})
        elif r["kind"] == "payroll_note":
            amendments.append({"source": r["source"], "type": "payroll_note",
                               "facts": r["facts"], "resolution": "salary_taken_from_settled_rows_and_confirmed_dates_only",
                               "reasoning": "same-source update; never invent income; rule (b)+(d)"})
        elif r["kind"] == "internal_transfer_pair":
            amendments.append({"source": r["source"], "type": "internal_transfer_pair",
                               "resolution": "paired_debit_credit_netted",
                               "reasoning": "bank-confirmed internal transfer; rule (a)"})

    # ---- de-dup: linked_event_id lifecycle + internal-transfer netting ----
    # The link alone never decides cash treatment; status does. Linked rows
    # that are refunds/valuations/reversals of an earlier row are marked so
    # Agent 2 counts cash once.
    by_id = {ev["event_id"]: ev for ev in user_events}
    duplicates: dict[str, str] = {}
    for ev in user_events:
        link = (ev.get("linked_event_id") or "").strip()
        if link and link in by_id:
            earlier = by_id[link]
            same_cash = (
                ev["category"] == earlier["category"]
                or ev["event_type"] in ("refund", "investment_valuation")
                or earlier["event_type"] in ("refund", "investment_valuation")
            )
            if same_cash and ev["status"] in IGNORE_STATUSES | {"settled"}:
                # Refund/valuation/reversal representation of the same lifecycle.
                # Keep the earlier cash row; mark this one duplicate unless it is
                # itself a distinct settled cash movement on another date.
                if ev["event_type"] in ("refund", "investment_valuation") or (
                    ev["amount_home"] == earlier["amount_home"]
                    and ev["direction"] != earlier["direction"]
                ):
                    duplicates[ev["event_id"]] = link
                    provenance[ev["event_id"]]["rule"] = (
                        "duplicate_of:" + link + ":linked_lifecycle")
                    provenance[ev["event_id"]]["sources"].append(
                        "linked_event_id:" + link)
    # Internal transfer pairs: same-day opposite-direction equal amounts.
    # Only net when a bank message confirms, else keep safer (count both).
    transfer_confirmed = any(r["kind"] == "internal_transfer_pair" for r in msg_rules)
    if transfer_confirmed:
        buckets: dict = defaultdict(list)
        for ev in user_events:
            if ev["event_id"] in duplicates or ev["status"] not in CASH_STATUSES:
                continue
            buckets[(ev["_settle"], ev["amount_home"])].append(ev)
        for key, grp in buckets.items():
            debits = [e for e in grp if e["direction"] == "debit"]
            credits = [e for e in grp if e["direction"] == "credit"]
            while debits and credits:
                d = debits.pop()
                c = credits.pop()
                # net the credit side (keep the debit as the cash outflow)
                duplicates[c["event_id"]] = d["event_id"]
                provenance[c["event_id"]]["rule"] = (
                    "netted_internal_transfer_with:" + d["event_id"])
                amendments.append({"source": "bank_transfer_note",
                                   "type": "internal_transfer_netted",
                                   "event_id": c["event_id"],
                                   "resolution": "credit_side_netted_debit_kept",
                                   "reasoning": "bank-confirmed same-holder transfer; rule (a)"})

    live = [ev for ev in user_events if ev["event_id"] not in duplicates]

    # ---- split cash-affecting buckets ----
    confirmed_future_income: list[dict] = []
    pending_scheduled_debits: list[dict] = []
    for ev in live:
        if ev["status"] in IGNORE_STATUSES:
            continue
        if ev["direction"] == "non_cash":
            continue
        if ev["direction"] == "credit":
            if _is_countable_credit(ev):
                # settled income is reflected in opening balance; scheduled
                # confirmed salary counts on settlement date (Agent 2 uses it).
                if ev["status"] == "scheduled":
                    confirmed_future_income.append({
                        "event_id": ev["event_id"], "amount_home": ev["amount_home"],
                        "settlement_date": ev["_settle"], "description": ev["description"],
                        "provenance": provenance[ev["event_id"]]})
            continue
        # debits: pending + scheduled + settled-future all reserve cash
        if ev["status"] in ("pending", "scheduled"):
            pending_scheduled_debits.append({
                "event_id": ev["event_id"], "amount_home": ev["amount_home"],
                "settlement_date": ev["_settle"], "status": ev["status"],
                "category": ev["category"], "description": ev["description"],
                "provenance": provenance[ev["event_id"]]})
    pending_scheduled_debits.sort(key=lambda d: (d["settlement_date"] or date.max, d["event_id"]))
    confirmed_future_income.sort(key=lambda d: (d["settlement_date"] or date.max, d["event_id"]))

    # ---- recurring detection (history-backed only) ----
    # Group settled debits by category; recurring iff >=3 occurrences with
    # median interval 25-35 days. Forecast value: p90 for essentials
    # (conservative), median for flexibles.
    settled_debits = [ev for ev in live
                      if ev["direction"] == "debit" and ev["status"] == "settled"]
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for ev in settled_debits:
        by_cat[ev["category"]].append(ev)
    recurring_expenses: list[dict] = []
    for cat, rows in sorted(by_cat.items()):
        rows.sort(key=lambda r: (r["_settle"] or date.min, r["event_id"]))
        if len(rows) < 3:
            continue
        dates = [r["_settle"] for r in rows if r["_settle"] is not None]
        if len(dates) < 3:
            continue
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        med_gap = median(gaps)
        if not (25 <= med_gap <= 35):
            continue
        amounts = [r["amount_home"] for r in rows]
        flex_vals = {r["flexibility"] for r in rows}
        flexibility = next(iter(flex_vals)) if len(flex_vals) == 1 else "mixed"
        is_flex_cat = (cat in willing_reduce) or (cat in willing_stop)
        is_flex_flag = any(v in ("reducible", "stoppable", "reducible_or_stoppable")
                           for v in flex_vals)
        flexible = bool(is_flex_cat and is_flex_flag and cat not in protect)
        essential = not flexible
        base = _p90(amounts) if essential else median(amounts)
        if rent_hike_pct and cat == "rent":
            base = round(base * (1 + rent_hike_pct / 100.0), 2)
        recurring_expenses.append({
            "series_key": f"{user_id}|{cat}",
            "category": cat,
            "essential": essential,
            "flexible": flexible,
            "flexibility": flexibility,
            "protected": cat in protect,
            "count": len(rows),
            "median_interval_days": med_gap,
            "avg_amount": round(sum(amounts) / len(amounts), 2),
            "median_amount": round(median(amounts), 2),
            "p90_amount": round(_p90(amounts), 2),
            "forecast_amount": round(base, 2),
            "minimum_allowed_amount": next(
                (r.get("minimum_allowed_amount", "") for r in rows
                 if (r.get("minimum_allowed_amount") or "").strip()), ""),
            "last_date": max(dates),
            "event_ids": [r["event_id"] for r in rows[-3:]],
            "representative_event_id": rows[-1]["event_id"],
        })

    state = {
        "user_id": user_id,
        "home_currency": home,
        "current_balance": balance,
        "minimum_balance_to_keep": minimum,
        "financial_priorities": _split_list(prof.get("financial_priorities", "")),
        "protected_categories": sorted(protect),
        "reducible_categories": sorted(willing_reduce),
        "stoppable_categories": sorted(willing_stop),
        "payment_methods_user_will_consider": _split_list(
            prof.get("payment_methods_user_will_consider", "")),
        "max_installment_months": (prof.get("max_installment_months") or "").strip() or None,
        "recurring_expenses": recurring_expenses,
        "confirmed_future_income": [
            {**i, "settlement_date": i["settlement_date"].isoformat()
             if isinstance(i["settlement_date"], date) else None}
            for i in confirmed_future_income
        ],
        "pending_scheduled_debits": [
            {**d, "settlement_date": d["settlement_date"].isoformat()
             if isinstance(d["settlement_date"], date) else None}
            for d in pending_scheduled_debits
        ],
        "amendments": amendments,
        "quarantine": quarantine,
        "ocr_applied": ocr_applied,
        "duplicates": duplicates,
        "provenance": provenance,
        "stats": {
            "n_events": len(user_events),
            "n_live": len(live),
            "n_duplicates": len(duplicates),
            "n_recurring_series": len(recurring_expenses),
        },
    }
    return state


def build_all_states(user_ids: list[str] | None = None) -> dict[str, dict]:
    """Build states for many users with shared cached inputs (one disk read)."""
    profiles = load_profiles()
    events = load_events()
    fx_idx = build_fx_index(load_rates())
    ocr = load_ocr_cache()
    messages = load_messages()
    if user_ids is None:
        user_ids = sorted(profiles)
    return {u: build_user_state(u, profiles, events, fx_idx, ocr, messages)
            for u in user_ids}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Agent 1: inspect clean user state")
    ap.add_argument("--user", required=True, help="user_id e.g. user_03")
    ap.add_argument("--compact", action="store_true",
                    help="omit per-event provenance for readability")
    args = ap.parse_args()
    s = build_user_state(args.user)
    if args.compact:
        s = {k: v for k, v in s.items() if k != "provenance"}
    print(json.dumps(s, indent=1, default=str))