# Dataset coverage — what is implemented, what is intentionally left out

Verified 2026-09-13 against `dataset/` + `problem_statement.md` + `AGENTS.md` §6.
Eval shape: 250 requests, 250 unique users (strictly 1:1), 16 blank-amount
events, 215 messages, 790 payment options. Zero messages are sent after their
user's eval `request_date`, so Stage 1's per-user (not per-request) state build
cannot leak future info into eval forecasts.

## Implemented (read + used in the pipeline)

| File | Rows | Used where | Columns used |
|---|---|---|---|
| `financial_profiles.csv` | 275 | `stage1` via `state_builder` | all: balance, `minimum_balance_to_keep`, `home_currency`, protected/reduce/stop categories, `payment_methods_user_will_consider`, `max_installment_months` (`""` = no installments), `financial_priorities` (stored in state for grounding; ranking itself is the locked 6-step) |
| `financial_events.csv` | 25342 | `stage1` + `forecast/income` | all: `event_type`/`category`/`direction`/`status` classification, `linked_event_id` lifecycle dedup, `flexibility` + `minimum_allowed_amount` for spending changes, `description` for one-off filters, `currency` + `settlement_date` FX |
| `exchange_rates.csv` | 134 | `state_builder.fx_convert` | `rate_date` + pair + `rate`; exact → most-recent-prior → next-future fallback, logged in provenance |
| `requests.csv` | 250 (`request_26`–`275`) | `stage2` + `stage3` | all structured fields; `request_text` is read but carries no extra math (spec defines no type-specific rules) |
| `request_payment_options.csv` | 790 | `stage3` via `decide` | `payment_option_id` schedule rebuilt exactly; `total_payable_amount` for min-total ranking (covers `financing_fee`); duration via `common.months_span` whole-months (LOCKED) |
| `messages.csv` | 215 (39 event-linked, 128 request-linked, 28 both) | `stage1` firewall/rules + `forecast/income` time-filtered overrides | `message_text` facts-only, `related_event_id` amend/confirm, `sent_at` cutoff in income (`<= request_date`), `source_type` employer payroll detection; `request_id` content is applied (time-filtered) but is not itself a filter — equivalent here because eval is 1 request/user and 0 messages postdate their eval request |
| `images.csv` + `media/images/*.png` | 16/16 | `vision_extract` → `state/image_cache.json` | `image_id` ↔ `related_event_id`; all 16 images map 1:1 to the 16 blank-amount events (verified), so amount extraction is the complete required use |
| `output.csv` (template) | 250 blank | header/order reference in `validate.EXPECTED_COLS` | header only |

## Intentionally left out (per guidelines, not gaps)

1. **`sample_requests.csv` labels are never used for eval predictions.** Guideline:
   format/style reference only. Implemented as: `validate.py` style cross-check
   + `code/eval_samples.py` diagnostic self-score (20/25 status on samples).
   Wiring sample answers into eval logic would be hardcoding and is forbidden.
2. **`request_type` / `request_text` drive no type-specific math.** The spec
   lists types but defines zero type-dependent rules; all types share the same
   90-day safety + ranking contract. Changing behavior by type would invent
   unsupported rules.
3. **Image non-amount content (dates/terms) is not OCR'd.** The spec's required
   image use is blank-amount extraction ("Do not treat a blank amount as
   zero"), which is fully implemented + cached. No image in `images.csv` exists
   beyond the 16 blank-linked receipts, so there is no standalone image
   evidence left unprocessed.
4. **`financial_priorities` does not alter ranking.** Ranking order is locked
   (deadline > no-changes > min-total > earlier > fewer > lowest option id).
   Priorities are preserved in state for explanation grounding, not math.
5. **Per-request message scoping beyond time cutoff.** Would matter with
   multi-request users or post-request messages; eval has neither (250 unique
   users, 0 late messages — verified). A per-request state rebuild is noted as
   future hardening, not an eval-correctness gap.

## Deliberate modeling calls (defended in code, verified by tests)

- **Salary streams, not one lump.** Settled salary credits are grouped by
  description signature (`forecast/income.py::_detect_streams`). The lumped
  history is tried first (unchanged behavior wherever it already detects
  monthly); only then do live per-earner groups project (dead groups >60 days
  stale never project). Paydays step by calendar day-of-month, not fixed
  timedeltas (Dec 15 + 30d = Jan 14 would drift off real payday cycles).
  Diagnostic self-score on samples: 20/25 status (see `code/eval_samples.py`).
- **Capacity dates kept on preference-blocked rows** (spec's independence
  note), documented in `validate.py`.
- **Image provenance is machine + manual.** `code/verify_images.py` cross-checks
  all 16 cached amounts against local RapidOCR text (16/16 found, 0 billed
  tokens); results persist in `image_cache.json::_ocr_check` and are cited in
  `evaluation/usage_report.md`. `usage_log.json == []` on a green run is
  correct: zero *live* model calls happened (cache hits only).
- **Ranking rule 1 > rule 2 is unit-tested** (`tests/test_ranking.py`):
  a completing plan with changes beats a non-completing plan without changes.

## How to verify this file's claims

```bash
python3 code/eval_samples.py
code/.venv/bin/python code/main.py   # or: python3 code/main.py
```
