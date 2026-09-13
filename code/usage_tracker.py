"""Usage tracker: every LLM/vision call goes through log_call().

Writes raw list to code/state/usage_log.json (required by Stage 3).
Also mirrors to the legacy llm_tracker JSONL so older packaging keeps working.
Builds sibling evaluation/usage_report.md (never nested inside code/).

Secrets are never stored here; API keys come from env vars only.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from common import EVAL_DIR, STATE_DIR, USAGE_LOG_JSON, USAGE_REPORT_MD, REQUESTS_CSV
except ImportError:  # pragma: no cover - direct script use
    from code.common import EVAL_DIR, STATE_DIR, USAGE_LOG_JSON, USAGE_REPORT_MD, REQUESTS_CSV  # type: ignore

LEGACY_LOG = STATE_DIR.parent / ".usage_log.jsonl"

PRICE_PER_1K = {
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "claude-3-5-sonnet": (0.003, 0.015),
    "gemini-1.5-flash": (0.00035, 0.00105),
    "manual-vision-review": (0.0, 0.0),
    "local-ocr": (0.0, 0.0),
    "local": (0.0, 0.0),
}


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def read_records() -> list:
    if not USAGE_LOG_JSON.exists():
        return []
    try:
        with open(USAGE_LOG_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_records(records: list) -> None:
    _ensure_state_dir()
    with open(USAGE_LOG_JSON, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=1, sort_keys=True)


def log_call(provider: str, model: str, input_tokens: int = 0,
             output_tokens: int = 0, num_calls: int = 1,
             purpose: str = "", image_id: str = "") -> dict:
    """Log one model usage record. Thread-safe enough for this pipeline."""
    in_price, out_price = PRICE_PER_1K.get(model, (0.0, 0.0))
    cost = (input_tokens / 1000.0) * in_price + (output_tokens / 1000.0) * out_price
    record = {
        "provider": provider,
        "model": model,
        "calls": int(num_calls),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "estimated_cost_usd": round(cost, 6),
        "purpose": purpose,
        "image_id": image_id,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }
    records = read_records()
    # Merge with identical provider/model/purpose bucket to keep file small?
    # No: keep every call as its own entry for auditability.
    records.append({k: v for k, v in record.items() if k != "logged_at" or True})
    _write_records(records)
    # Legacy mirror for backward compat with llm_tracker/package.
    try:
        with open(LEGACY_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "provider": provider, "model": model, "calls": int(num_calls),
                "input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
                "estimated_cost_usd": round(cost, 6),
            }) + "\n")
    except OSError:
        pass
    return record


def reset() -> None:
    _ensure_state_dir()
    _write_records([])
    if LEGACY_LOG.exists():
        LEGACY_LOG.unlink()


def n_requests() -> int:
    with open(REQUESTS_CSV, encoding="utf-8") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def build_usage_report() -> Path:
    """Aggregate usage_log.json (+ cached vision) into sibling evaluation/usage_report.md."""
    records = read_records()
    # Cached vision pass lives in state/image_cache.json with its own accounting.
    try:
        from common import IMAGE_CACHE_JSON
    except ImportError:
        from code.common import IMAGE_CACHE_JSON  # type: ignore
    try:
        with open(IMAGE_CACHE_JSON, encoding="utf-8") as fh:
            cache = json.load(fh)
            meta = cache.get("_tokens", {})
            ocr_check = cache.get("_ocr_check", {})
        if meta:
            records = list(records) + [{
                "provider": meta.get("provider", "none"),
                "model": meta.get("model", "manual-vision-review"),
                "calls": meta.get("calls", 0),
                "input_tokens": meta.get("input_tokens", 0),
                "output_tokens": meta.get("output_tokens", 0),
                "estimated_cost_usd": 0.0,
            }]
    except (OSError, ValueError):
        ocr_check = {}
    n = n_requests()
    per_model: dict = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "provider": ""})
    for r in records:
        m = per_model[r.get("model", "unknown")]
        m["provider"] = r.get("provider", "")
        m["calls"] += int(r.get("calls", 1))
        m["in"] += int(r.get("input_tokens", 0))
        m["out"] += int(r.get("output_tokens", 0))
        m["cost"] += float(r.get("estimated_cost_usd", 0.0))
    tot_calls = sum(v["calls"] for v in per_model.values())
    tot_in = sum(v["in"] for v in per_model.values())
    tot_out = sum(v["out"] for v in per_model.values())
    tot_cost = sum(v["cost"] for v in per_model.values())
    tot_tokens = tot_in + tot_out
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    if ocr_check.get("checked") and ocr_check.get("matched") == ocr_check.get("checked"):
        ocr_note = (f"* Machine provenance: all {ocr_check['matched']}/{ocr_check['checked']} cached amounts "
                    f"verified present in local RapidOCR text ({ocr_check.get('engine', 'local OCR')}); "
                    "see image_cache.json `_ocr_check`. Re-run code/verify_images.py to re-verify.")
    else:
        ocr_note = ("* Machine provenance: run code/verify_images.py to cross-check cached "
                    "amounts against local RapidOCR text.")
    lines = ["# Token Usage Report -- final full-dataset run", "",
             f"Requests evaluated: {n}", "", "## Per-model totals", "",
             "| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) |",
             "|---|---|---|---|---|---|---|"]
    if per_model:
        for model in sorted(per_model):
            v = per_model[model]
            lines.append(f"| {v['provider']} | {model} | {v['calls']} | {v['in']} | {v['out']} | {v['in'] + v['out']} | {v['cost']:.6f} |")
    else:
        lines.append("| - | (no LLM API calls; fully deterministic local run) | 0 | 0 | 0 | 0 | 0.000000 |")
    lines += ["", "## Overall totals", "",
              f"* Model calls: {tot_calls}", f"* Input tokens: {tot_in}",
              f"* Output tokens: {tot_out}", f"* Total tokens: {tot_tokens}",
              f"* Average tokens/request: {tot_tokens / n:.2f}" if n else "* Average tokens/request: 0.00",
              f"* Estimated total cost (USD): {tot_cost:.6f}",
              f"* Estimated cost/request (USD): {tot_cost / n:.6f}" if n else "* Estimated cost/request (USD): 0.000000",
              "", "Notes:",
              "* Blank-amount receipts were extracted once via vision review and",
              "  cached in code/state/image_cache.json (zero billed tokens on repeats);",
              "  full-dataset runs reuse the cache deterministically with 0 repeat calls.",
              ocr_note,
              "* Forecasting/decision math is local and deterministic.",
              "* No API keys or credentials are included in this report.", ""]
    USAGE_REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    return USAGE_REPORT_MD
