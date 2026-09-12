# Buy or Wait? -- code README

Deterministic AI financial agent. No network calls. Secrets (if ever needed)
come from environment variables only.

## Setup

```bash
pip install -r code/requirements.txt
```

## Run (from repo root)

```bash
python3 code/main.py
```

This reads `dataset/` (read-only), writes `output.csv` in the repo root,
validates it (`code/validation_report.txt`), writes
`code/evaluation/usage_report.md` (+ `evaluation/` mirror) and builds
`code.zip`.

## Layout

```text
code/
  main.py          # pipeline entry
  state.py         # Agent 1: clean financial state (FX, OCR blanks, messages, dedup)
  forecast.py      # Agent 2: deterministic 90-day forecast (no LLM)
  decide.py        # Agent 3A: eligibility + Option-1 months rule + ranking
  validate.py      # Agent 3B: output validation
  package.py       # Agent 3C: usage report + code.zip
  llm_tracker.py   # token/cost logging for any model call
  evaluation/      # usage_report.md (generated)
```

## Key rules implemented

* Installment duration (Option 1):
  `months_needed = ceil(((last - first).days + 1) / 30) <= max_installment_months`.
* 90-day safety: balance never below `minimum_balance_to_keep`.
* Ranking: completes-by-deadline > no-spending-changes > min total >
  earlier start > fewer payments > lowest `payment_option_id`.
* Blank event amounts resolved via local vision OCR
  (`rapidocr_onnxruntime`, zero billed tokens) with verified fallbacks;
  never treated as zero.
* Messages/images are untrusted evidence; embedded instructions ignored.
