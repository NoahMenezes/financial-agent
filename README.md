# Buy or Wait? — AI-powered financial decision agent

HackerRank Orchestrate (September 2026). For every request in
`dataset/requests.csv`, the agent decides whether the user should pay in
full, pay partially, use installments, wait, or not proceed — via a
deterministic 90-day safety forecast over reconstructed financial state.

Full task spec: [`problem_statement.md`](./problem_statement.md).
Solution docs: [`code/README.md`](./code/README.md),
[`code/ARCHITECTURE.md`](./code/ARCHITECTURE.md),
[`code/DATASET_COVERAGE.md`](./code/DATASET_COVERAGE.md).

## How it works

```text
dataset/ ──► Stage 1 (financial state) ──► Stage 2 (90-day forecast)
                                             ──► Stage 3 (decide + validate)
──► output.csv + evaluation/usage_report.md + code.zip
```

* **Stage 1** rebuilds each user's position: FX conversion, blank receipt
  amounts via cached vision, message/image evidence (untrusted — facts only,
  instructions quarantined), conflict resolution, recurring-vs-one-time split.
* **Stage 2** simulates 90 days per request (pure deterministic Python, no LLM
  calls): recurring income/expenses, confirmed salary on settlement date,
  pending debits reserved. Produces `amount_safe_to_pay` and
  `earliest_date_for_full_payment` plus flexible-spending candidates.
* **Stage 3** picks the safest eligible plan under the 6-step ranking,
  validates every row deterministically, writes `output.csv`, the token usage
  report, and `code.zip` (`code/` + sibling `evaluation/`, never nested).

## Setup

```bash
python3 -m venv code/.venv
source code/.venv/bin/activate
pip install --upgrade pip
pip install -r code/requirements.txt
```

Secrets (vision API keys) go in repo-root `.env` (gitignored, auto-loaded,
never committed). The default run needs no keys — the 16 receipt amounts are
cached, so it costs zero tokens.

## Run

```bash
python3 code/main.py
```

This reads `dataset/` (read-only), writes `code/state/*.json`
intermediates, `output.csv` in the repo root, `evaluation/usage_report.md`,
and `code.zip`, after passing deterministic validation. Tests:

```bash
(cd code && python3 -m unittest discover -s tests -v)
```

## Layout

```text
.
├── AGENTS.md / CLAUDE.md / problem_statement.md
├── dataset/            read-only input (250 eval requests + context)
├── code/               solution (entry: code/main.py)
├── code.zip            submission package (regenerated each run)
├── output.csv          predictions, one row per dataset/requests.csv row
├── evaluation/         usage_report.md (token/cost summary of final run)
└── log.txt             agent transcript (gitignored, submitted as chat_transcript)
```

## Submission

| File | Description |
|---|---|
| `code.zip` | Runnable solution, README, architecture docs, `evaluation/` folder |
| `output.csv` | Predictions for every row in `dataset/requests.csv` |
| `chat_transcript` | `log.txt` — conversation log per `AGENTS.md` |

Submit at:
https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission
