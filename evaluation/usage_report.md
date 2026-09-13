# Token Usage Report -- final full-dataset run

Requests evaluated: 250

## Per-model totals

| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) |
|---|---|---|---|---|---|---|
| none | manual-vision-review | 0 | 0 | 0 | 0 | 0.000000 |

## Overall totals

* Model calls: 0
* Input tokens: 0
* Output tokens: 0
* Total tokens: 0
* Average tokens/request: 0.00
* Estimated total cost (USD): 0.000000
* Estimated cost/request (USD): 0.000000

Notes:
* Blank-amount receipts were extracted once via vision review and
  cached in code/state/image_cache.json (zero billed tokens on repeats);
  full-dataset runs reuse the cache deterministically with 0 repeat calls.
* Machine provenance: all 16/16 cached amounts verified present in local RapidOCR text (rapidocr_onnxruntime (local, 0 billed tokens)); see image_cache.json `_ocr_check`. Re-run code/verify_images.py to re-verify.
* Forecasting/decision math is local and deterministic.
* No API keys or credentials are included in this report.
