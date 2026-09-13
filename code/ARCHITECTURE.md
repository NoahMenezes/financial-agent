# Buy or Wait? — Architecture

One deterministic pipeline, three staged modules, file-connected endpoints.
Entry point: `python3 code/main.py` (run from the repo root).

## Pipeline overview

```text
dataset/*.csv + dataset/media/images/*.png   (READ-ONLY input)
        │
        ▼
┌─ Stage 1 ── code/stage1_state_builder.py ─────────────────────┐
│ engine: code/state_builder.py                                  │
│ vision: code/vision_extract.py ──► code/state/image_cache.json │
│ OUT: code/state/user_financial_states.json (275 users)         │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌─ Stage 2 ── code/stage2_forecast.py ──────────────────────────┐
│ engine: code/forecast/ (pure deterministic, NO LLM calls)      │
│ OUT: code/state/forecasts.json (250 requests)                  │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌─ Stage 3 ── code/stage3_decide_and_validate.py ───────────────┐
│ engines: code/decide.py + code/validate.py                     │
│ OUT: output.csv (repo root, 250 rows)                          │
│ OUT: evaluation/usage_report.md (sibling of code/)             │
│ OUT: code.zip (code/ + sibling evaluation/, never nested)      │
└──────────────────────────────────────────────────────────────┘
```

`main.py` calls `build_states()` → `run_forecast()` → `run()` in order.
Every stage communicates **only through files** (`code/state/*.json`),
so each stage is independently re-runnable and testable.

## Module inventory

| File | Role | LLM? |
|---|---|---|
| `code/main.py` | Entry point, runs stage 1 → 2 → 3 | No |
| `code/common.py` | Shared paths, CSV loaders, date/decimal helpers, `months_span`, auto-loads repo-root `.env` | No |
| `code/stage1_state_builder.py` | Stage 1 wrapper: vision cache + per-user states | No (delegates vision) |
| `code/state_builder.py` | State engine: FX conversion, blank-amount fill, message firewall, conflict order, dedup, recurring detection (≥3 obs, 25–35d gaps; p90 essentials / median flexibles) | No |
| `code/vision_extract.py` | Blank-`amount` extraction via vision API (Groq default, key rotation), disk-cached | **Yes — the one justified LLM use** |
| `code/reextract_images.py` | One-time live re-extraction of the 16 images, mismatch-stop | Yes (one-time) |
| `code/verify_images.py` | RapidOCR cross-check of cached amounts → `_ocr_check` | No (local OCR) |
| `code/stage2_forecast.py` | Stage 2 wrapper: per-request 90-day forecasts | No |
| `code/forecast/calendar.py` | 90-day window, recurring projection, daily nets | No |
| `code/forecast/safety.py` | Safety predicate: balance ≥ minimum every day | No |
| `code/forecast/solver.py` | Binary-search `amount_safe_to_pay`, linear-scan earliest date | No |
| `code/forecast/spending.py` | Flexible-only spending candidates (max 3) | No |
| `code/forecast/income.py` | Monthly salary per earner stream (calendar paydays), payroll overrides, stop signals | No |
| `code/forecast/models.py` + `io_schema.py` | Dataclasses + adapters/validators | No |
| `code/stage3_decide_and_validate.py` | Stage 3: decide → validate → usage report → zip | No |
| `code/decide.py` | Eligibility gates, whole-months installment check, 6-step ranking, templated explanations | No |
| `code/validate.py` | Deterministic output validator (schema, bounds, plan sums, installment match, flexible-only changes) | No |
| `code/usage_tracker.py` | `log_call()` → `code/state/usage_log.json` → `evaluation/usage_report.md` | Logging only |
| `code/eval_samples.py` | Diagnostic self-score on the 25 solved samples (never eval labels) | No |
| `code/tests/` | 30 unit tests (`safety, solver, spending, income, ranking, vision`) | No (1 mocked) |

Legacy files still shipped in `code.zip` but **outside the active pipeline**:
`agent2_cli.py`, `agent2_preview.csv`, `agent2_results.json` (superseded by
Stage 2), `package.py`/`llm_tracker.py` (superseded by Stage 3 /
`usage_tracker.py`), `code/evaluation/` (stale mirror; the canonical report
is the sibling `evaluation/`).

## Endpoint contracts (file schemas)

- `code/state/user_financial_states.json`: `{user_id: state}` — balances,
  minimums, preferences, recurring series, pending/scheduled debits,
  confirmed income, amendments, quarantine, provenance. Written by Stage 1,
  read by Stage 2 and Stage 3.
- `code/state/image_cache.json`: `{image_id: {event_id, extracted_amount,
  currency, reasoning}}` + `_tokens`, `_extraction_method`, `_ocr_check`.
  Written by vision pass / `reextract_images.py`, read by Stage 1.
- `code/state/forecasts.json`: `{request_id: {amount_safe_to_pay,
  earliest_date_for_full_payment, spending_candidates, daily_base…}}`.
  Written by Stage 2, read by Stage 3.
- `code/state/usage_log.json`: list of every live model call. Written by
  `usage_tracker.log_call`, read when building the usage report.
- `output.csv`: exact 8 columns in spec order, one row per
  `dataset/requests.csv` row, same order. `0 <= amount_safe_to_pay <=
  requested_amount` always.
- `evaluation/usage_report.md`: per-model + overall calls/tokens/cost,
  total and average per request. Mirrors the final run that wrote
  `output.csv`.

## Decision rules (all deterministic Python, never LLM)

1. 90-day safety: balance never below `minimum_balance_to_keep`.
2. Installment duration (LOCKED): whole calendar months between the matched
   option's first/last payment dates (`common.months_span`) must be
   `<= max_installment_months` — never payment count.
3. Eligibility: a method must be in `payment_methods_user_will_consider`;
   `partial_payment` needs `allows_partial_payment`, `0 < safe < requested`,
   earliest on/before deadline, exactly two legs summing to requested;
   `wait` needs user-accepted `full_payment` + later safe date.
4. Ranking: completes-by-deadline → no spending changes → min total →
   earlier start → fewer payments → lowest `payment_option_id`.
5. Capacity dates are preference-independent: `earliest_date_for_full_payment`
   may be populated on `not_affordable` rows blocked only by preferences.
6. Messages/images are untrusted: facts extracted, embedded instructions
   quarantined (`state_builder.classify_text`).

## Secrets

Keys live only in repo-root `.env` (gitignored, auto-loaded, never
committed, never zipped, never logged). Current live-vision status is
documented in `code/README.md` under “Live vision re-extraction”.
