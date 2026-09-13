"""Shared config, CSV loaders, currency conversion, date helpers.

Single import point for all stage modules. Stdlib only, deterministic.
Dataset is READ-ONLY; state/ and evaluation/ are generated at runtime.
"""
from __future__ import annotations

import csv
import os
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CODE_DIR.parent


def _load_dotenv() -> None:
    """Load repo-root (or code/) `.env` into os.environ without overriding.

    Stdlib-only: KEY=VALUE lines, '#' comments, optional quotes. Lets
    `python3 code/main.py` pick up GROQ_KEY_1/GROQ_KEY_2 with no manual export.
    """
    for path in (REPO_ROOT / ".env", CODE_DIR / ".env"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("'\"").strip()
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()
DATASET = REPO_ROOT / "dataset"
STATE_DIR = CODE_DIR / "state"
EVAL_DIR = REPO_ROOT / "evaluation"
OUTPUT_CSV = REPO_ROOT / "output.csv"

PROFILES_CSV = DATASET / "financial_profiles.csv"
EVENTS_CSV = DATASET / "financial_events.csv"
RATES_CSV = DATASET / "exchange_rates.csv"
REQUESTS_CSV = DATASET / "requests.csv"
OPTIONS_CSV = DATASET / "request_payment_options.csv"
MESSAGES_CSV = DATASET / "messages.csv"
IMAGES_CSV = DATASET / "images.csv"
MEDIA_DIR = DATASET / "media" / "images"

STATES_JSON = STATE_DIR / "user_financial_states.json"
IMAGE_CACHE_JSON = STATE_DIR / "image_cache.json"
FORECASTS_JSON = STATE_DIR / "forecasts.json"
USAGE_LOG_JSON = STATE_DIR / "usage_log.json"
USAGE_REPORT_MD = EVAL_DIR / "usage_report.md"

TWOPLACES = Decimal("0.01")


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def to_decimal(x) -> Decimal:
    if isinstance(x, Decimal):
        return x.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return Decimal(str(x)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_profiles() -> dict:
    return {r["user_id"]: r for r in _read_csv(PROFILES_CSV)}


def load_events() -> list[dict]:
    return _read_csv(EVENTS_CSV)


def load_rates() -> list[dict]:
    return _read_csv(RATES_CSV)


def load_messages() -> list[dict]:
    return _read_csv(MESSAGES_CSV)


def load_images_index() -> list[dict]:
    return _read_csv(IMAGES_CSV)


def load_requests() -> list[dict]:
    return _read_csv(REQUESTS_CSV)


def load_options() -> list[dict]:
    return _read_csv(OPTIONS_CSV)


def months_span(first: date, last: date) -> int:
    """LOCKED clarification #1: whole months between first and last payment date.

    Derived from the matched payment_option_id's actual dates, NOT from
    number_of_payments. A 3-payment quarterly option spanning 9 months must be
    rejected when max_installment_months < 9 even though the count looks small.
    Single-payment options span 0 months (always eligible on duration).
    """
    if last is None or first is None or last < first:
        return 0
    m = (last.year - first.year) * 12 + (last.month - first.month)
    if last.day < first.day:
        m -= 1
    return max(m, 0)


def installment_last_date(first: date, n: int, freq_days: int) -> date:
    from datetime import timedelta

    if n <= 1 or not freq_days:
        return first
    return first + timedelta(days=(n - 1) * freq_days)
