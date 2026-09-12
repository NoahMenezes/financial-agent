"""Stage 1 -- Financial State Builder.

Reads dataset/*.csv + media PNGs (via vision_extract cache), writes:
  code/state/user_financial_states.json  (one clean object per user_id)
  code/state/image_cache.json            (image_id -> amount, via vision_extract)

Delegates heavy lifting to the tested state_builder engine so behavior stays
identical; this module owns the FILE endpoints required by the pipeline.
No LLM calls except cached vision fills inside vision_extract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))

from common import (  # noqa: E402
    IMAGE_CACHE_JSON,
    STATES_JSON,
    STATE_DIR,
    load_events,
    load_requests,
)
import vision_extract  # noqa: E402
from state_builder import build_all_states  # noqa: E402


def build_states(user_ids: list[str] | None = None) -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # 1) Ensure vision cache exists (migrates legacy ocr_cache.json; 0 repeat cost).
    events = load_events()
    blanks = {e["event_id"] for e in events if not (e.get("amount") or "").strip()}
    vision_extract.ensure_cache_for_events(blanks)
    # 2) Build states with the tested engine (reads vision via compat shim).
    # Spec: one object per user in financial_profiles.csv. Default to ALL users
    # so user_financial_states.json covers profiles beyond the eval requests.
    if user_ids is None:
        user_ids = None  # build_all_states defaults to all profiles
    states = build_all_states(user_ids)
    with open(STATES_JSON, "w", encoding="utf-8") as fh:
        json.dump(states, fh, indent=1, sort_keys=True, default=str)
    return states


def main() -> int:
    states = build_states()
    print(f"stage1: wrote {len(states)} states -> {STATES_JSON}")
    print(f"stage1: image cache -> {IMAGE_CACHE_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
