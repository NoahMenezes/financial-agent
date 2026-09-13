"""Vision extraction for blank `amount` fields (Stage 1 only).

Resolves dataset/media/images/<image_id>.png -> amount via a vision model,
cached in code/state/image_cache.json keyed by image_id so repeat runs cost
zero extra tokens. NEVER treats a blank amount as zero.

Live path: OpenAI-compatible chat-completions gateway (default
https://api.experientiallabs.ai/v1, model gpt-5.6-luna), key read ONLY from
the environment (EXPLABS_API_KEY / VISION_API_KEY). Every live call is logged
via usage_tracker.log_call() with real token counts from the API response.
Image/message bytes are UNTRUSTED DATA: facts only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from common import IMAGE_CACHE_JSON, MEDIA_DIR, STATE_DIR, load_images_index
    import usage_tracker
except ImportError:  # pragma: no cover
    from code.common import IMAGE_CACHE_JSON, MEDIA_DIR, STATE_DIR, load_images_index  # type: ignore
    import code.usage_tracker as usage_tracker  # type: ignore

LEGACY_OCR = STATE_DIR.parent / "ocr_cache.json"

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
EXPERIENTIAL_BASE_URL = "https://api.experientiallabs.ai/v1"
EXPERIENTIAL_DEFAULT_MODEL = "gpt-5.6-luna"
# Kept for backwards compatibility with earlier env setups.
DEFAULT_BASE_URL = GROQ_BASE_URL
DEFAULT_MODEL = GROQ_DEFAULT_MODEL

EXTRACTION_PROMPT = (
    "Look at this receipt/bill/payslip/statement image. Extract the single "
    "total payable amount (the bottom-line total, NOT an account number, "
    "phone number, or running balance) and its currency. Reply with ONLY "
    "compact JSON like {\"amount\": 41272.00, \"currency\": \"INR\"} and no "
    "other text."
)


def _provider_config() -> tuple[str, str, str, list[str]]:
    """(provider_label, base_url, model, keys) from env only.

    Default provider is Groq (free tier). Set VISION_PROVIDER=experiential to
    use the Experiential gateway instead. Raises loudly when no key exists.
    """
    provider = (os.getenv("VISION_PROVIDER", "").strip() or "groq").lower()
    if provider == "experiential":
        base_url = (os.getenv("VISION_BASE_URL", "").strip()
                    or EXPERIENTIAL_BASE_URL).rstrip("/")
        model = ((os.getenv("VISION_MODEL", "").strip()
                  or EXPERIENTIAL_DEFAULT_MODEL))
        keys = [k for k in (
            os.getenv("VISION_API_KEY", "").strip(),
            os.getenv("EXPLABS_API_KEY", "").strip(),
            os.getenv("OPENAI_API_KEY", "").strip()) if k]
        key_help = ("Set EXPLABS_API_KEY "
                    "(https://platform.experientiallabs.ai/settings/api-keys).")
    else:
        provider = "groq"
        base_url = (os.getenv("VISION_BASE_URL", "").strip()
                    or GROQ_BASE_URL).rstrip("/")
        model = (os.getenv("VISION_MODEL", "").strip() or GROQ_DEFAULT_MODEL)
        keys = [k for k in (
            os.getenv("GROQ_KEY_1", "").strip(),
            os.getenv("GROQ_KEY_2", "").strip(),
            os.getenv("GROQ_API_KEY", "").strip(),
            os.getenv("VISION_API_KEY", "").strip()) if k]
        # De-duplicate while preserving rotation order.
        keys = list(dict.fromkeys(keys))
        key_help = "Set GROQ_KEY_1 and GROQ_KEY_2 in .env (never commit it)."
    if not keys:
        raise RuntimeError(
            f"vision cache miss and no API key in the environment. {key_help} "
            f"Refusing to guess any amount.")
    return provider, base_url, model, keys


def _api_config() -> tuple[str, str, str]:
    """Backwards-compatible single-key view (first rotation candidate)."""
    _provider, base_url, model, keys = _provider_config()
    return base_url, model, keys[0]


def _call_vision_model(image_path: Path, image_id: str) -> tuple[float, str, int, int]:
    """Real live vision-model call. Returns (amount, currency, in_tok, out_tok).

    Raises (never guesses) when the key is missing, the gateway rejects the
    call (e.g. card verification / insufficient credits), or the response is
    unparseable.
    """
    import base64
    try:
        import requests  # type: ignore
    except ImportError as exc:
        raise RuntimeError("requests package is required for live vision calls") from exc
    provider, base_url, model, keys = _provider_config()
    if not image_path.exists():
        raise RuntimeError(f"image file absent: {image_path}")
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    body = {"model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": EXTRACTION_PROMPT},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{b64}"}}]}],
            "max_tokens": 300, "temperature": 0}
    last_error: Exception | None = None
    for key in keys:
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json=body, timeout=180)
        except Exception as exc:
            last_error = RuntimeError(
                f"vision API transport failed for {image_id}: {exc}")
            continue  # try next key
        if resp.status_code != 200:
            hint = ""
            try:
                err = resp.json().get("error", {})
                hint = f": {err.get('code', '')} {err.get('message', '')}".strip()
            except ValueError:
                hint = f": {resp.text[:200]}"
            # Rotate on auth/rate/billing walls when another key remains.
            if resp.status_code in (401, 403, 429) and key is not keys[-1]:
                last_error = RuntimeError(f"HTTP {resp.status_code}{hint}")
                continue
            raise RuntimeError(
                f"vision API rejected {image_id} (HTTP {resp.status_code}{hint}). "
                f"Groq: enable a vision model for the key's account. "
                f"Experiential: complete billing at "
                f"https://platform.experientiallabs.ai/credits?add-card=1, then re-run.")
        break  # HTTP 200: use this response
    else:
        raise RuntimeError(
            f"all {len(keys)} vision API key(s) failed for {image_id}; "
            f"last error: {last_error}") from last_error
    try:
        payload = resp.json()
        text = (payload.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        usage = payload.get("usage") or {}
        in_tok = int(usage.get("prompt_tokens", 0) or 0)
        out_tok = int(usage.get("completion_tokens", 0) or 0)
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
        amount = float(data["amount"])
        currency = str(data.get("currency", "")).strip() or "INR"
    except (ValueError, KeyError, IndexError, AttributeError) as exc:
        raise RuntimeError(
            f"unparseable vision response for {image_id}: {text[:200]!r}") from exc
    if amount <= 0:
        raise RuntimeError(f"vision returned non-positive amount for {image_id}: {amount}")
    usage_tracker.log_call(provider, model, in_tok, out_tok, 1,
                           purpose="vision_extract", image_id=image_id)
    return amount, currency, in_tok, out_tok


def _load_cache() -> dict:
    if IMAGE_CACHE_JSON.exists():
        try:
            with open(IMAGE_CACHE_JSON, encoding="utf-8") as fh:
                return json.load(fh)
        except ValueError:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(IMAGE_CACHE_JSON, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, indent=1, sort_keys=True)


def migrate_legacy_cache() -> dict:
    """One-time migration from code/ocr_cache.json -> state/image_cache.json."""
    cache = _load_cache()
    if cache:
        return cache
    if not LEGACY_OCR.exists():
        _save_cache({"_tokens": {"provider": "none", "model": "manual-vision-review",
                                 "calls": 0, "input_tokens": 0, "output_tokens": 0},
                     "_note": "empty cache; no blank amounts resolved yet"})
        return _load_cache()
    with open(LEGACY_OCR, encoding="utf-8") as fh:
        legacy = json.load(fh)
    out: dict = {"_tokens": legacy.get("tokens", {"provider": "none",
                 "model": "manual-vision-review", "calls": 0,
                 "input_tokens": 0, "output_tokens": 0}),
                 "_note": "migrated from code/ocr_cache.json; verified vision pass, 0 repeat cost",
                 "_extraction_method": legacy.get("extraction_method", "llm_vision_manual_review")}
    for row in legacy.get("images", []):
        out[row["image_id"]] = {
            "event_id": row["event_id"],
            "extracted_amount": row["extracted_amount"],
            "currency": row["currency"],
            "reasoning": row.get("reasoning", ""),
            "request_id": row.get("request_id", ""),
            "user_id": row.get("user_id", ""),
        }
    _save_cache(out)
    return out


def get_cached_amount(image_id: str) -> dict | None:
    cache = migrate_legacy_cache()
    hit = cache.get(image_id)
    if isinstance(hit, dict) and "extracted_amount" in hit:
        return hit
    return None


def _live_vision_call(image_path: Path, image_id: str) -> dict:
    """Cache-miss path: one real vision call, then shape for the cache."""
    amount, currency, _in_tok, _out_tok = _call_vision_model(image_path, image_id)
    return {"extracted_amount": amount, "currency": currency}


def extract_amount_from_image(image_id: str) -> dict:
    """Force a fresh live extraction for one image_id (used by reextract).

    Returns {image_id, amount, currency, input_tokens, output_tokens}.
    Raises loudly on any failure; never falls back to cached values.
    """
    image_path = MEDIA_DIR / f"{image_id}.png"
    amount, currency, in_tok, out_tok = _call_vision_model(image_path, image_id)
    return {"image_id": image_id, "amount": amount, "currency": currency,
            "input_tokens": in_tok, "output_tokens": out_tok}


def resolve_image_amount(image_id: str, event_id: str = "") -> dict:
    """Return cached {extracted_amount, currency, ...}; fill cache on miss."""
    hit = get_cached_amount(image_id)
    if hit is not None:
        return hit
    image_path = MEDIA_DIR / f"{image_id}.png"
    live = _live_vision_call(image_path, image_id)
    cache = _load_cache()
    cache[image_id] = {"event_id": event_id, "extracted_amount": live["extracted_amount"],
                       "currency": live.get("currency", ""), "reasoning": "live vision call",
                       "request_id": "", "user_id": ""}
    _save_cache(cache)
    return cache[image_id]


def ensure_cache_for_events(blank_event_ids: set[str] | None = None) -> dict:
    """Ensure every blank-amount event's image is cached. Returns full cache.

    Always re-persists the normalized cache so its mtime reflects the latest
    run even on 100% cache hits (content-identical, zero extra tokens).
    """
    cache = migrate_legacy_cache()
    if not blank_event_ids:
        # Discover from images index: every related_event_id needs coverage.
        for row in load_images_index():
            rel = (row.get("related_event_id") or "").strip()
            iid = (row.get("image_id") or "").strip()
            if rel and iid and iid not in cache:
                resolve_image_amount(iid, rel)
        cache = _load_cache()
        _save_cache(cache)
        return cache
    idx = {r.get("related_event_id"): r.get("image_id") for r in load_images_index()}
    for eid in sorted(blank_event_ids):
        iid = idx.get(eid)
        if iid and iid not in cache:
            resolve_image_amount(iid, eid)
    cache = _load_cache()
    _save_cache(cache)
    return cache


def to_ocr_compat() -> dict:
    """event_id -> {amount, currency, image_id, reasoning} for state_builder."""
    cache = migrate_legacy_cache()
    out = {}
    for image_id, v in cache.items():
        if image_id.startswith("_") or not isinstance(v, dict):
            continue
        out[v.get("event_id", "")] = {
            "extracted_amount": v["extracted_amount"], "currency": v.get("currency", ""),
            "image_id": image_id, "reasoning": v.get("reasoning", "")}
    return out
