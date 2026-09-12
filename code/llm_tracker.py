"""Token/cost tracking for every LLM / vision API call in the pipeline.

All model calls anywhere (OCR-vision fallback, explanation drafting, etc.)
must go through `log_call`. Local deterministic computation (RapidOCR,
regex parsers, Decimal math) is logged with zero tokens/cost so the usage
report is complete even for a zero-LLM run.

Secrets are never stored here -- API keys are read from env vars only.
"""
from __future__ import annotations

import json
import os
import threading

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".usage_log.jsonl")
_lock = threading.Lock()

# Rough per-1K-token USD prices (used only for estimation in the report).
PRICE_PER_1K = {
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "claude-3-5-sonnet": (0.003, 0.015),
    "gemini-1.5-flash": (0.00035, 0.00105),
    "local-ocr": (0.0, 0.0),
    "local": (0.0, 0.0),
}


def log_call(provider: str, model: str, input_tokens: int = 0,
             output_tokens: int = 0, num_calls: int = 1) -> dict:
    """Append one usage record to the JSONL log. Thread-safe."""
    in_price, out_price = PRICE_PER_1K.get(model, (0.0, 0.0))
    cost = (input_tokens / 1000.0) * in_price + (output_tokens / 1000.0) * out_price
    record = {
        "provider": provider,
        "model": model,
        "calls": int(num_calls),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "estimated_cost_usd": round(cost, 6),
    }
    with _lock:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    return record


def read_records() -> list:
    if not os.path.exists(LOG_PATH):
        return []
    out = []
    with open(LOG_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def reset() -> None:
    with _lock:
        if os.path.exists(LOG_PATH):
            os.remove(LOG_PATH)
