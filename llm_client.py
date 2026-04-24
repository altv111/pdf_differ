"""LLM client helpers for hybrid diff classification.

Supports two modes:
- stub mode (default): deterministic local classification output.
- real OpenAI mode (optional): enabled via environment flag.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib import error, request

BASE_DIR = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into process environment."""

    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_project_env() -> None:
    """Load top-level project `.env` file if present."""

    load_env_file(BASE_DIR / ".env")


def _env_true(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_llm_settings() -> Dict[str, Any]:
    """Expose runtime model/provider settings and key presence indicators."""

    provider = os.environ.get("LLM_PROVIDER", "openai")
    model = os.environ.get("LLM_MODEL", "gpt-5.4")
    return {
        "provider": provider,
        "model": model,
        "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic_key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "real_calls_enabled": _env_true("LLM_ENABLE_REAL_CALLS", False),
    }


load_project_env()


def build_llm_payload(section_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare the structured payload consumed by the model adapter."""

    return {
        "task": "classify_document_diff",
        "labels": ["editorial", "slight", "significant"],
        "llm_settings": get_llm_settings(),
        "section": {
            "section_id": section_payload.get("section_id"),
            "section_title": section_payload.get("section_title"),
            "before_text": section_payload.get("before_text", ""),
            "after_text": section_payload.get("after_text", ""),
            "diff_score": section_payload.get("diff_score"),
            "metadata": section_payload.get("metadata", {}),
        },
    }


def _default_post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_s: float) -> Dict[str, Any]:
    """POST JSON with stdlib urllib and decode JSON response."""

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _extract_label_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object containing classification fields from model text."""

    if not text:
        return None
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _first_output_text(resp: Dict[str, Any]) -> str:
    """Best-effort text extraction from OpenAI Responses API output."""

    if isinstance(resp.get("output_text"), str) and resp["output_text"].strip():
        return resp["output_text"]

    outputs = resp.get("output", [])
    for item in outputs:
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                return content["text"]
    return ""


def _classify_with_openai(
    prepared_payload: Dict[str, Any],
    section_payload: Dict[str, Any],
    post_json: Callable[[str, Dict[str, str], Dict[str, Any], float], Dict[str, Any]] = _default_post_json,
) -> Dict[str, Any]:
    """Call OpenAI Responses API and parse classification JSON."""

    model = prepared_payload["llm_settings"]["model"]
    api_key = os.environ.get("OPENAI_API_KEY", "")
    api_base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
    timeout_s = float(os.environ.get("LLM_TIMEOUT_SECONDS", "25"))
    retries = int(os.environ.get("LLM_RETRIES", "2"))

    system_prompt = (
        "You classify section-level document changes. "
        "Return strict JSON with keys: label, confidence, rationale. "
        "label must be one of editorial, slight, significant."
    )
    user_payload = {
        "section_title": prepared_payload["section"]["section_title"],
        "before_text": prepared_payload["section"]["before_text"],
        "after_text": prepared_payload["section"]["after_text"],
        "diff_score": prepared_payload["section"]["diff_score"],
    }

    req_body = {
        "model": model,
        "temperature": 0,
        "max_output_tokens": 220,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}]},
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{api_base.rstrip('/')}/responses"

    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = post_json(url, headers, req_body, timeout_s)
            text = _first_output_text(resp)
            parsed = _extract_label_json(text) or {}
            label = str(parsed.get("label", "slight")).strip().lower()
            if label not in {"editorial", "slight", "significant"}:
                label = "slight"
            confidence = float(parsed.get("confidence", 0.6))
            confidence = max(0.0, min(1.0, confidence))
            rationale = str(parsed.get("rationale", "Model classification."))
            return {
                "label": label,
                "confidence": round(confidence, 4),
                "rationale": rationale,
                "model": model,
                "prompt_version": "v1-openai",
                "prepared_payload": prepared_payload,
                "stub": False,
                "raw_response": resp,
            }
        except (error.HTTPError, error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.5 * (2**attempt))
                continue

    # Safe fallback keeps pipeline running.
    fallback_label = section_payload.get("llm_mock_label", "slight")
    fallback_confidence = float(section_payload.get("llm_mock_confidence", 0.51))
    return {
        "label": fallback_label,
        "confidence": round(fallback_confidence, 4),
        "rationale": f"OpenAI call failed, fallback to stub: {last_error}",
        "model": model,
        "prompt_version": "v1-openai-fallback",
        "prepared_payload": prepared_payload,
        "stub": True,
    }


def classify_with_llm(section_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Classify one section with optional real LLM call and safe fallback.

    Real-call mode is enabled only when:
    - LLM_ENABLE_REAL_CALLS=true
    - LLM_PROVIDER=openai
    - OPENAI_API_KEY is set
    """

    payload = build_llm_payload(section_payload)
    settings = payload["llm_settings"]

    if (
        settings["real_calls_enabled"]
        and settings["provider"].lower() == "openai"
        and settings["openai_key_present"]
    ):
        return _classify_with_openai(payload, section_payload)

    label = section_payload.get("llm_mock_label", "slight")
    confidence = float(section_payload.get("llm_mock_confidence", 0.51))
    return {
        "label": label,
        "confidence": round(confidence, 4),
        "rationale": "Stubbed classifier result; set LLM_ENABLE_REAL_CALLS=true for real API calls.",
        "model": None,
        "prompt_version": "v1-stub",
        "prepared_payload": payload,
        "stub": True,
    }
