from typing import Any

from depguard.agent.llm import gemini_models, make_llm
from depguard.config import Settings


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_gemini_models_keep_their_order_without_blanks_or_repeats() -> None:
    assert gemini_models(" gemini-a, gemini-b,,gemini-a ") == ["gemini-a", "gemini-b"]
    assert gemini_models("") == []


def test_each_configured_gemini_model_is_a_fallback_with_the_short_timeout() -> None:
    llm = make_llm(
        settings(
            groq_api_key="test",
            gemini_api_key="test",
            gemini_models="gemini-a,gemini-b",
            gemini_timeout_seconds=7,
        )
    )

    assert [p.model_name for p in llm.fallbacks] == ["gemini-a", "gemini-b"]
    assert all(p.model.timeout == 7 for p in llm.fallbacks)  # type: ignore[attr-defined]


def test_without_a_gemini_key_there_is_no_fallback() -> None:
    assert make_llm(settings(groq_api_key="test")).fallbacks == ()
