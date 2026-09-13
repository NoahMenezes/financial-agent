"""Vision caller tests: parsing, rotation, loud failures (mocked, no network)."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vision_extract

IMG = Path(__file__).resolve().parent.parent.parent / "dataset" / "media" / "images" / "image_03.png"


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _ok_payload(content='{"amount": 41272.00, "currency": "INR"}',
                prompt=1200, completion=25):
    return {"choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


def _clear_env():
    for v in ("VISION_API_KEY", "EXPLABS_API_KEY", "OPENAI_API_KEY",
              "GROQ_KEY_1", "GROQ_KEY_2", "GROQ_API_KEY",
              "VISION_BASE_URL", "VISION_MODEL", "VISION_PROVIDER"):
        os.environ.pop(v, None)


class TestVisionCall(unittest.TestCase):
    def setUp(self):
        _clear_env()

    def test_missing_key_raises_loudly(self):
        with self.assertRaises(RuntimeError) as cm:
            vision_extract._call_vision_model(IMG, "image_03")
        self.assertIn("GROQ_KEY_1", str(cm.exception))

    def test_groq_defaults_used(self):
        os.environ["GROQ_KEY_1"] = "test-key"
        seen = {}
        fake_requests = type("R", (), {})()

        def fake_post(url, headers=None, json=None, timeout=None):
            seen.update(url=url, auth=headers.get("Authorization"),
                        model=json["model"])
            return _Resp(200, _ok_payload())
        fake_requests.post = fake_post
        with patch.dict(sys.modules, {"requests": fake_requests}):
            amt, cur, itok, otok = vision_extract._call_vision_model(IMG, "image_03")
        self.assertEqual((amt, cur, itok, otok), (41272.00, "INR", 1200, 25))
        self.assertTrue(seen["url"].startswith("https://api.groq.com/openai/v1/"))
        self.assertEqual(seen["auth"], "Bearer test-key")
        self.assertEqual(seen["model"], "meta-llama/llama-4-scout-17b-16e-instruct")

    def test_success_logs_provider_model_tokens(self):
        os.environ["GROQ_KEY_1"] = "test-key"
        fake_requests = type("R", (), {})()
        fake_requests.post = lambda *a, **k: _Resp(200, _ok_payload())
        logged = []
        with patch.dict(sys.modules, {"requests": fake_requests}):
            with patch.object(vision_extract.usage_tracker, "log_call",
                              side_effect=lambda *a, **k: logged.append((a, k)) or {}):
                vision_extract._call_vision_model(IMG, "image_03")
        self.assertEqual(len(logged), 1)
        self.assertEqual(
            logged[0][0][:2], ("groq", "meta-llama/llama-4-scout-17b-16e-instruct"))

    def test_rotation_to_second_key_on_429(self):
        os.environ["GROQ_KEY_1"] = "key-one"
        os.environ["GROQ_KEY_2"] = "key-two"
        fake_requests = type("R", (), {})()
        auths = []

        def fake_post(url, headers=None, json=None, timeout=None):
            auths.append(headers.get("Authorization"))
            if headers.get("Authorization") == "Bearer key-one":
                return _Resp(429, {"error": {"code": "rate_limit_exceeded",
                                             "message": "slow down"}})
            return _Resp(200, _ok_payload())
        fake_requests.post = fake_post
        with patch.dict(sys.modules, {"requests": fake_requests}):
            amt, cur, _i, _o = vision_extract._call_vision_model(IMG, "image_03")
        self.assertEqual((amt, cur), (41272.00, "INR"))
        self.assertEqual(auths, ["Bearer key-one", "Bearer key-two"])

    def test_all_keys_failed_raises(self):
        os.environ["GROQ_KEY_1"] = "key-one"
        fake_requests = type("R", (), {})()
        fake_requests.post = lambda *a, **k: _Resp(
            404, {"error": {"code": "model_not_found", "message": "no access"}})
        with patch.dict(sys.modules, {"requests": fake_requests}):
            with self.assertRaises(RuntimeError) as cm:
                vision_extract._call_vision_model(IMG, "image_03")
        self.assertIn("model_not_found", str(cm.exception))

    def test_unparseable_raises(self):
        os.environ["GROQ_KEY_1"] = "test-key"
        fake_requests = type("R", (), {})()
        fake_requests.post = lambda *a, **k: _Resp(
            200, _ok_payload(content="no json here"))
        with patch.dict(sys.modules, {"requests": fake_requests}):
            with self.assertRaises(RuntimeError):
                vision_extract._call_vision_model(IMG, "image_03")


if __name__ == "__main__":
    unittest.main()
