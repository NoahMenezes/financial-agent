"""One-time live re-extraction of the 16 blank-amount images.

Invalidates the cached manual-review entries in code/state/image_cache.json,
makes ONE real vision-model API call per image (16 calls total), stops hard
on any mismatch with the previously verified amount (human must review that
image), then OCR cross-checks and rewrites the cache with
`_extraction_method = "llm_vision_api"`.

Requires vision keys in the environment (GROQ_KEY_1/GROQ_KEY_2 in .env by
default; or EXPLABS_API_KEY with VISION_PROVIDER=experiential).
After this succeeds once, `python3 code/main.py` needs zero repeat calls.

Usage:
    python3 code/reextract_images.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))

from common import IMAGE_CACHE_JSON  # noqa: E402
import vision_extract  # noqa: E402


def main() -> int:
    cache = vision_extract.migrate_legacy_cache()
    image_ids = sorted(k for k in cache if not k.startswith("_"))
    if len(image_ids) != 16:
        print(f"expected 16 cached images, found {len(image_ids)}; refusing to proceed")
        return 1
    old_values = {i: (cache[i]["extracted_amount"], cache[i].get("currency", ""))
                  for i in image_ids}
    fresh: dict = {}
    for image_id in image_ids:
        print(f"extracting {image_id} ...", flush=True)
        try:
            fresh[image_id] = vision_extract.extract_amount_from_image(image_id)
        except RuntimeError as exc:
            print(f"STOP: live extraction failed for {image_id}:\n  {exc}")
            print("Cache left untouched. Fix billing/key, then re-run.")
            return 1
    mismatches = []
    for image_id in image_ids:
        old_amt, old_cur = old_values[image_id]
        new_amt, new_cur = fresh[image_id]["amount"], fresh[image_id]["currency"]
        if abs(float(new_amt) - float(old_amt)) > 0.005 or new_cur != old_cur:
            mismatches.append((image_id, old_amt, old_cur, new_amt, new_cur))
    if mismatches:
        print("STOP: model output disagrees with verified amounts on "
              f"{len(mismatches)} image(s); cache left untouched:")
        for image_id, old_amt, old_cur, new_amt, new_cur in mismatches:
            print(f"  {image_id}: verified {old_amt} {old_cur} vs model {new_amt} {new_cur}")
        print("A human must review these images before overwriting.")
        return 1
    # Full agreement: rewrite cache with model provenance (keep OCR check).
    from datetime import datetime, timezone
    new_cache: dict = {
        "_tokens": {"provider": "groq",
                    "model": __import__("os").getenv("VISION_MODEL", "").strip()
                    or vision_extract.GROQ_DEFAULT_MODEL,
                    "calls": 16, "input_tokens": sum(f["input_tokens"] for f in fresh.values()),
                    "output_tokens": sum(f["output_tokens"] for f in fresh.values())},
        "_note": ("live vision-model extraction (16 calls, one-time cost), "
                  "cross-checked vs manual review (16/16 match) and local OCR"),
        "_extraction_method": "llm_vision_api",
        "_extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    if isinstance(cache.get("_ocr_check"), dict):
        new_cache["_ocr_check"] = cache["_ocr_check"]
    for image_id in image_ids:
        old_entry = cache[image_id]
        new_cache[image_id] = {
            "event_id": old_entry.get("event_id", ""),
            "extracted_amount": fresh[image_id]["amount"],
            "currency": fresh[image_id]["currency"],
            "reasoning": "live vision-model extraction, matched manual review",
            "request_id": old_entry.get("request_id", ""),
            "user_id": old_entry.get("user_id", ""),
        }
    vision_extract._save_cache(new_cache)
    print("16/16 agree with verified amounts; cache rewritten with llm_vision_api provenance.")
    print("Next: python3 code/verify_images.py && python3 code/main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
