import os
from pathlib import Path

from llm_client import (
    _classify_with_openai,
    _extract_label_json,
    build_llm_payload,
    classify_with_llm,
    load_env_file,
)


def test_load_env_file_sets_values(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        """
# comment
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.4
OPENAI_API_KEY=test-key
""".strip(),
        encoding="utf-8",
    )

    os.environ.pop("LLM_PROVIDER", None)
    os.environ.pop("LLM_MODEL", None)
    os.environ.pop("OPENAI_API_KEY", None)

    load_env_file(env)

    assert os.environ.get("LLM_PROVIDER") == "openai"
    assert os.environ.get("LLM_MODEL") == "gpt-5.4"
    assert os.environ.get("OPENAI_API_KEY") == "test-key"


def test_build_payload_contains_llm_settings() -> None:
    payload = build_llm_payload({"section_id": "s1", "section_title": "Intro"})
    assert "llm_settings" in payload
    assert "provider" in payload["llm_settings"]
    assert "model" in payload["llm_settings"]


def test_extract_label_json_parses_embedded_json() -> None:
    parsed = _extract_label_json('some text {"label":"significant","confidence":0.91,"rationale":"x"} end')
    assert parsed is not None
    assert parsed["label"] == "significant"


def test_classify_with_llm_uses_stub_when_real_calls_disabled(monkeypatch) -> None:
    monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "false")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = classify_with_llm({"section_title": "X"})
    assert out["stub"] is True


def test_openai_adapter_parses_response(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.4")

    prepared = build_llm_payload(
        {
            "section_title": "Principle X",
            "before_text": "old",
            "after_text": "new",
        }
    )

    def fake_post(url, headers, payload, timeout_s):  # noqa: ANN001
        del url, headers, payload, timeout_s
        return {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"label":"editorial","confidence":0.88,"rationale":"tiny wording change"}',
                        }
                    ]
                }
            ]
        }

    out = _classify_with_openai(prepared, {}, post_json=fake_post)
    assert out["stub"] is False
    assert out["label"] == "editorial"
    assert out["confidence"] == 0.88


def test_openai_adapter_falls_back_on_error(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    prepared = build_llm_payload({"section_title": "X", "before_text": "a", "after_text": "b"})

    def fail_post(url, headers, payload, timeout_s):  # noqa: ANN001
        del url, headers, payload, timeout_s
        raise TimeoutError("network")

    out = _classify_with_openai(prepared, {"llm_mock_label": "slight"}, post_json=fail_post)
    assert out["stub"] is True
    assert out["label"] == "slight"
