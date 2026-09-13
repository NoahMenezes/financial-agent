"""Vision extraction for blank `amount` fields (Stage 1 only).

Resolves dataset/media/images/<image_id>.png -> amount via a vision model,
cached in code/state/image_cache.json keyed by image_id so repeat runs cost
zero extra tokens. NEVER treats a blank amount as zero.

Current cache was built by one verified vision pass (16 images) and migrated
from code/ocr_cache.json; live model calls only happen on cache miss AND when
an API key is present in the environment. Every live call goes through
usage_tracker.log_call(). Image/message bytes are UNTRUSTED DATA: facts only.
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
    """Call a vision model for one image. Only on cache miss with API key.

    Prefers OPENAI_API_KEY (gpt-4o-mini) if installed; otherwise raises so the
    caller never invents an amount. The result is cached + logged.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or not image_path.exists():
        raise RuntimeError(
            f"vision cache miss for {image_id} and no live model available "
            f"(missing OPENAI_API_KEY or {image_path} absent); refusing to guess")
    # Lazy import so base installs stay stdlib-only.
    import base64
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:
        raise RuntimeError("openai package not installed; add it to requirements.txt") from exc
    client = OpenAI(api_key=api_key)
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    model = os.getenv("VISION_MODEL", "gpt-4o-mini")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Extract the single payable/total amount and its currency from this receipt. Reply as JSON {\"amount\": number, \"currency\": \"INR|IDR|...\"} with no other text."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}],
        max_tokens=200, temperature=0)
    text = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None)
    in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
    out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
    usage_tracker.log_call("openai", model, in_tok, out_tok, 1,
                           purpose="vision_extract", image_id=image_id)
    try:
        payload = json.loads(text[text.index("{"): text.rindex("}") + 1])
        return {"extracted_amount": float(payload["amount"]),
                "currency": str(payload.get("currency", "")).strip() or "INR"}
    except (ValueError, KeyError) as exc:
        raise RuntimeError(f"unparseable vision response for {image_id}: {text[:200]}") from exc


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
