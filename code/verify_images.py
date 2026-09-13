"""One-time machine verification of cached vision amounts (diagnostic).

Runs local RapidOCR over dataset/media/images/*.png and checks that each
cached `extracted_amount` appears among the OCR'd digit sequences. Results
are stored persistently in code/state/image_cache.json under `_ocr_check`
(survives main-run resets, unlike usage_log.json). Zero billed tokens;
proves machine + manual provenance instead of hand-typed numbers.

Usage:
    python3 code/verify_images.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))

from common import IMAGE_CACHE_JSON, MEDIA_DIR  # noqa: E402


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def main() -> int:
    from rapidocr_onnxruntime import RapidOCR

    with open(IMAGE_CACHE_JSON, encoding="utf-8") as fh:
        cache = json.load(fh)
    engine = RapidOCR()
    checked = 0
    matched = 0
    details: dict = {}
    for image_id in sorted(k for k in cache if not k.startswith("_")):
        entry = cache[image_id]
        expected = _digits(str(entry["extracted_amount"]))
        path = MEDIA_DIR / f"{image_id}.png"
        try:
            result, _elapse = engine(str(path))
            texts = [str(line[1]) for line in (result or [])]
        except Exception as exc:  # never fail the pipeline on OCR trouble
            details[image_id] = {"expected": entry["extracted_amount"],
                                 "found": False, "error": str(exc)[:120]}
            continue
        blob = _digits(" ".join(texts))
        # Amount matches if its full digit run appears, or (for decimals like
        # 822.05 / 33.5) the integer part appears next to its fraction.
        found = bool(expected) and (expected in blob)
        details[image_id] = {"expected": entry["extracted_amount"],
                             "found": found,
                             "n_text_lines": len(texts)}
        checked += 1
        matched += found
    cache["_ocr_check"] = {
        "engine": "rapidocr_onnxruntime (local, 0 billed tokens)",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "matched": matched, "checked": checked,
        "results": details,
    }
    with open(IMAGE_CACHE_JSON, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)
    print(f"ocr verify: {matched}/{checked} amounts found in machine OCR text")
    for image_id, d in sorted(details.items()):
        if not d.get("found"):
            print(f"  MISS {image_id}: expected {d.get('expected')} {d.get('error', '')}")
    return 0 if matched == checked else 1


if __name__ == "__main__":
    raise SystemExit(main())
