"""Buy or Wait? -- single pipeline entry point (three internal stages).

Usage:
    python3 code/main.py [--skip-package]

Data flow (file endpoints, in order):
  1. stage1_state_builder.build_states()
       dataset/*.csv + dataset/media/images/*.png
       -> code/state/user_financial_states.json + code/state/image_cache.json
  2. stage2_forecast.run_forecast()
       code/state/user_financial_states.json + dataset/requests.csv
       -> code/state/forecasts.json   (pure deterministic, no LLM calls)
  3. stage3_decide_and_validate.run()
       code/state/forecasts.json + code/state/user_financial_states.json
       + dataset/request_payment_options.csv + dataset/requests.csv
       -> output.csv (repo root) + evaluation/usage_report.md + code.zip

Every LLM call anywhere goes through usage_tracker.log_call(...).
Deterministic: sorted I/O, Decimal money, no randomness.
Secrets from environment variables only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CODE_DIR.parent
sys.path.insert(0, str(CODE_DIR))

import usage_tracker  # noqa: E402
import stage1_state_builder  # noqa: E402
import stage2_forecast  # noqa: E402
import stage3_decide_and_validate  # noqa: E402


def parse_args():
    ap = argparse.ArgumentParser(description="Buy or Wait? financial agent")
    ap.add_argument("--skip-package", action="store_true",
                    help="skip usage_report.md + code.zip packaging")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    usage_tracker.reset()
    print("stage 1/3: building financial states ...", flush=True)
    stage1_state_builder.build_states()
    print("stage 2/3: running 90-day forecasts ...", flush=True)
    stage2_forecast.run_forecast()
    print("stage 3/3: deciding, validating, packaging ...", flush=True)
    return stage3_decide_and_validate.run(skip_package=args.skip_package)


if __name__ == "__main__":
    raise SystemExit(main())
