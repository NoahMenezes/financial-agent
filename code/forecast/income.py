"""Recurring salary projection (Agent 2).

Agent 1 keeps settled income only in the opening balance and forwards
scheduled rows as confirmed_future_income. It does NOT project the next
monthly salary. Without that, 208/250 eval users show no future income and
the forecast collapses to ~0 safe (verified vs sample_requests).

This module restores the missing piece, deterministically:
  - settled `income/salary` credits are grouped by description signature
    (one group per earner/payroll stream: "Primary household salary" and
    "Second household income" are DIFFERENT streams; lumping them poisons
    cadence detection with 5-day interleaved gaps). The lumped history is
    tried first (unchanged behavior for today's projecting users); only when
    it fails cadence, each live description-group is tried on its own.
    Groups whose last pay is >60 days older than the newest settled salary
    are dead streams (e.g. a previous employer) and are never projected.
  - monthly cadence = >=3 points with median gap 25-35d;
  - base amount = LAST settled salary of that stream (reflects cuts);
  - paydays are projected on the same CALENDAR day-of-month (month-end
    clamped), not last_date + fixed timedelta (which drifts: Dec 15 + 30d =
    Jan 14, but payroll lands on the 15th);
  - employer payroll messages sent on/before request_date may override the
    amount (explicit amendment wins) and/or the next pay date. INSTRUCTION
    texts quarantined; only FACT notes with plausible amounts ([0.3x, 3x] of
    last salary) count. Future-dated messages ignored (no leak).
  - one-offs (bonus/arrears/invoice/payout/windfall) are NEVER projected.

Merged with Agent 1 scheduled rows downstream with +/-5d dedupe
(scheduled wins on collision).
"""

from __future__ import annotations

import calendar as _calendar
import re
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from .calendar import parse_date, to_decimal

# One-off top-ups that must never seed the monthly salary cycle.
NON_BASE_PAY = re.compile(
    r"commission|bonus|arrear|overtime|incentive|\bthr\b|allowance|reimburse",
    re.IGNORECASE,
)
# Last-paycheck markers: the job ended, do not project further income.
FINAL_PAY = re.compile(r"final|last\s+pay|closing|terminat|ended", re.IGNORECASE)
# Message-level income-stop signals (explicit cancellation wins).
STOP_SIGNALS = (
    "employment has ended",
    "employment ended",
    "no regular salary after",
    "seasonal contract has ended",
    "no off-season income",
    "contract has ended",
    "will not be renewed",
    "terminated",
    "no renewal has been confirmed",
)


def _norm_desc(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _collect_salary_rows(
    all_events: list[dict],
    user_id: str,
    home: str,
    fx_idx: dict,
    ocr: dict,
) -> tuple[list[tuple[date, Decimal, str]], date | None]:
    """All settled base-pay salary credits with normalized description.

    Returns ([(settle, amount_home, norm_desc)], final_pay_date).
    """
    # Local import to avoid cycle at module load; state_builder is Agent 1 code
    # reused read-only (FX + firewall helpers).
    from state_builder import _f, _parse_date, fx_convert

    rows: list[tuple[date, Decimal, str]] = []
    final_pay_date: date | None = None
    for ev in all_events:
        if ev.get("user_id") != user_id:
            continue
        if ev.get("event_type") != "income" or ev.get("category") != "salary":
            continue
        if ev.get("direction") != "credit" or ev.get("status") != "settled":
            continue
        if NON_BASE_PAY.search(ev.get("description", "")):
            continue  # commission/bonus/arrears are one-offs, never projected
        raw_s = (ev.get("amount") or "").strip()
        if not raw_s:
            hit = ocr.get(ev["event_id"])
            if not hit:
                continue  # never invent; skip (documented)
            raw_s = str(hit["extracted_amount"])
        raw = _f(raw_s)
        if raw is None or raw <= 0:
            continue
        ev_cur = (ev.get("currency") or home).strip() or home
        settle = _parse_date(ev.get("settlement_date") or ev.get("event_date"))
        if settle is None:
            continue
        prov: dict = {}
        val, _ = fx_convert(raw, ev_cur, home, settle, fx_idx, prov)
        rows.append((settle, to_decimal(val), _norm_desc(ev.get("description", ""))))
        if FINAL_PAY.search(ev.get("description", "")):
            final_pay_date = settle if final_pay_date is None else max(final_pay_date, settle)
    rows.sort()
    return rows, final_pay_date


def _settled_salary_history(
    all_events: list[dict],
    user_id: str,
    home: str,
    fx_idx: dict,
    ocr: dict,
) -> list[tuple[date, Decimal]]:
    rows, final = _collect_salary_rows(all_events, user_id, home, fx_idx, ocr)
    out = [(d, a) for d, a, _ in rows]
    return out, final


def detect_monthly_salary(
    history: list[tuple[date, Decimal]],
) -> dict | None:
    if len(history) < 3:
        return None
    dates = [d for d, _ in history]
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    med_gap = int(median(gaps))
    if not (25 <= med_gap <= 35):
        return None
    last_date, last_amt = history[-1]
    return {"interval": med_gap, "pay_day": last_date.day,
            "last_date": last_date, "last_amount": last_amt}


def _add_months(d: date, n: int) -> date:
    """Calendar-month step anchored to the payroll day-of-month (clamped)."""
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, _calendar.monthrange(y, m)[1]))


def _plausible_salary_candidates(amounts: list[float], last: Decimal) -> list[Decimal]:
    out: list[Decimal] = []
    for a in amounts:
        try:
            v = to_decimal(a)
        except Exception:
            continue
        if v <= 0:
            continue
        # Filter date fragments / refs: must be within [0.3x, 3x] of last pay.
        if v < last * Decimal("0.3") or v > last * Decimal("3"):
            continue
        out.append(v)
    # dedupe preserving order
    seen: set[Decimal] = set()
    uniq: list[Decimal] = []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def parse_payroll_override(
    messages: list[dict],
    user_id: str,
    request_date: date,
    last_amount: Decimal,
) -> tuple[Decimal | None, date | None]:
    """Return (override_amount, next_date_override) from employer FACT notes.

    - sent_at > request_date ignored.
    - INSTRUCTION class quarantined.
    - rent/invoice/refund/payout/windfall texts ignored (salary only).
    - next-date override: explicit 'replac/revis' with a facts date in
      [request_date-5d, request_date+40d] (e.g. moved to the 23rd).
    - amount override: single plausible candidate != last -> use it;
      multiple -> min (financially safer).
    """
    from state_builder import classify_text, extract_facts

    amt_override: Decimal | None = None
    date_override: date | None = None
    for m in messages:
        if m.get("user_id") != user_id:
            continue
        sent_raw = (m.get("sent_at") or "")[:10]
        sent = parse_date(sent_raw)
        if sent is not None and sent > request_date:
            continue
        text = m.get("message_text", "")
        if classify_text(text) != "FACT":
            continue
        low = text.lower()
        if not any(k in low for k in ("salar", "gaji", "payroll", "pay ")):
            continue
        if any(k in low for k in ("invoice", "faktur", "refund", "prize",
                                  "lottery", "payout", "market value",
                                  "transfer between your two accounts")):
            continue
        facts = extract_facts(text)
        cands = _plausible_salary_candidates(facts.get("amounts", []), last_amount)
        cands = [c for c in cands if c != last_amount]
        if cands:
            pick = cands[0] if len(cands) == 1 else min(cands)
            # Explicit amendment wins; if several messages, last-sent wins:
            # messages are processed in file order (chronological), so later
            # overwrites earlier deterministically.
            amt_override = pick
        if ("replac" in low or "revis" in low) and facts.get("dates"):
            for ds in facts["dates"]:
                d = parse_date(ds)
                if d is None:
                    continue
                if request_date - timedelta(days=5) <= d <= request_date + timedelta(days=40):
                    date_override = d  # later message overwrites
                    break
    return amt_override, date_override


def income_stopped_by_message(messages: list[dict], user_id: str, request_date: date) -> bool:
    """True if an employer message on/before request_date ends future pay."""
    from state_builder import classify_text

    for m in messages:
        if m.get("user_id") != user_id:
            continue
        sent = parse_date((m.get("sent_at") or "")[:10])
        if sent is not None and sent > request_date:
            continue
        text = m.get("message_text", "")
        if classify_text(text) == "INSTRUCTION":
            continue
        low = text.lower()
        if any(sig in low for sig in STOP_SIGNALS):
            return True
    return False


def _detect_streams(
    all_events: list[dict],
    user_id: str,
    home: str,
    fx_idx: dict,
    ocr: dict,
) -> list[dict]:
    """Monthly salary streams for one user (usually exactly one).

    Tries the lumped history first (identical to previous behavior). Only
    when lumping fails cadence (e.g. two earners interleaved at 5/25-day
    gaps), each live description-group is tried alone; dead groups (last pay
    >60 days older than the newest settled salary) are excluded.
    """
    rows, _final = _collect_salary_rows(all_events, user_id, home, fx_idx, ocr)
    if not rows:
        return []
    lumped = [(d, a) for d, a, _ in rows]
    det = detect_monthly_salary(lumped)
    if det is not None:
        return [det]
    newest = max(d for d, _, _ in rows)
    streams: list[dict] = []
    by_desc: dict[str, list[tuple[date, Decimal]]] = {}
    for d, a, g in rows:
        by_desc.setdefault(g, []).append((d, a))
    for g in sorted(by_desc):
        hist = sorted(by_desc[g])
        if (newest - hist[-1][0]).days > 60:
            continue  # dead stream (e.g. previous employer); never project
        det = detect_monthly_salary(hist)
        if det is not None:
            streams.append(det)
    return streams


def _project_stream(det: dict, date_override: date | None, amount: Decimal,
                    request_date: date, window_end: date) -> list[dict]:
    if date_override is not None:
        first = date_override
    else:
        first = _add_months(det["last_date"], 1)
        # fast-forward if last pay was long ago (e.g. data gap)
        months_ahead = 0
        while first < request_date and months_ahead < 14:
            first = _add_months(first, 1)
            months_ahead += 1
    occ: list[dict] = []
    d = first
    for _ in range(6):
        if d > window_end:
            break
        if d >= request_date:
            occ.append({"date": d, "amount": amount, "kind": "projected_salary"})
        d = _add_months(d, 1)
    return occ


def project_salary_occurrences(
    all_events: list[dict],
    messages: list[dict],
    user_id: str,
    home: str,
    fx_idx: dict,
    ocr: dict,
    request_date: date,
    window_end: date,
) -> list[dict]:
    _hist, final_pay = _settled_salary_history(all_events, user_id, home, fx_idx, ocr)
    if final_pay is not None and final_pay < request_date:
        return []  # 'Final employer payroll' already paid: job ended, no projection
    if income_stopped_by_message(messages, user_id, request_date):
        return []  # explicit cancellation wins over history
    streams = _detect_streams(all_events, user_id, home, fx_idx, ocr)
    if not streams:
        return []
    # Amount override is plausibility-gated per stream; the date override
    # (explicit payroll-date move) is shared across live streams.
    largest = max(streams, key=lambda s: s["last_amount"])
    _amt0, date_override = parse_payroll_override(
        messages, user_id, request_date, largest["last_amount"]
    )
    occ: list[dict] = []
    for det in sorted(streams, key=lambda s: s["last_amount"], reverse=True):
        amt_override, _d0 = parse_payroll_override(
            messages, user_id, request_date, det["last_amount"]
        )
        occ.extend(_project_stream(det, date_override,
                                   amt_override or det["last_amount"],
                                   request_date, window_end))
    occ.sort(key=lambda o: (o["date"], str(o["amount"])))
    return occ


def merge_income(
    scheduled: list[dict],
    projected: list[dict],
    request_date: date,
    window_end: date,
) -> list[dict]:
    """Combine Agent-1 scheduled rows + projected salary; dedupe +/-5d.

    Scheduled (explicit) wins on collision. Returns Agent-1-shaped rows
    [{amount_home, settlement_date}] for calendar.build_daily_nets.
    """
    merged: list[dict] = []
    sched_dates: list[date] = []
    for inc in scheduled:
        sd = parse_date(inc.get("settlement_date"))
        if sd is None or sd < request_date or sd > window_end:
            continue
        merged.append({"amount_home": float(inc["amount_home"]),
                       "settlement_date": sd.isoformat()})
        sched_dates.append(sd)
    for p in projected:
        d = p["date"]
        if d < request_date or d > window_end:
            continue
        if any(abs((d - s).days) <= 5 for s in sched_dates):
            continue  # explicit scheduled row already covers this pay cycle
        merged.append({"amount_home": float(p["amount"]), "settlement_date": d.isoformat()})
    merged.sort(key=lambda r: (r["settlement_date"], str(r["amount_home"])))
    return merged
