from __future__ import annotations

from typing import Any

import pytest

from app.config import get_settings
from app.harness.input_gate import run_input_gate
from app.services.llm_query_rewrite import build_llm_query_rewrite, select_query_rewrite
from app.services.query_rewrite import rewrite_query


def test_llm_rewrite_default_disabled(run_async: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_REWRITE_ENABLED", "false")
    monkeypatch.setenv("LLM_PROVIDER", "mock_shadow")
    get_settings.cache_clear()

    async def scenario() -> None:
        deterministic = rewrite_query("我在北京鼓楼，想吃川菜，你直接帮我选一个")
        result = await build_llm_query_rewrite(
            "我在北京鼓楼，想吃川菜，你直接帮我选一个",
            deterministic=deterministic,
        )
        selected, selection = select_query_rewrite(deterministic, result)

        assert result.enabled is False
        assert result.status == "disabled"
        assert selected == deterministic
        assert selection is not None
        assert selection.accepted is False

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_mock_llm_rewrite_adds_missing_area_and_keeps_input_gate_deterministic(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_REWRITE_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "mock_shadow")
    monkeypatch.setenv("LLM_MODEL", "mock-shadow-v0")
    get_settings.cache_clear()

    async def scenario() -> None:
        message = "我在北京鼓楼，想吃川菜，你直接帮我选一个"
        deterministic = rewrite_query(message)
        assert "area" not in deterministic.extracted_slots

        result = await build_llm_query_rewrite(message, deterministic=deterministic)
        selected, selection = select_query_rewrite(deterministic, result)
        gate = run_input_gate(message, rewrite_result=selected)

        assert result.status == "success"
        assert selection is not None
        assert selection.accepted is True
        assert selected.extracted_slots["area"] == "鼓楼"
        assert gate.route_priority == "area_food"
        assert gate.location_state == "in_area"
        assert gate.should_enter_loop is True
        assert gate.extracted_slots["area"] == "鼓楼"

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_low_confidence_llm_rewrite_is_not_selected(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_REWRITE_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "mock_shadow")
    get_settings.cache_clear()

    async def scenario() -> None:
        message = "我在北京低置信鼓楼，想吃川菜，你直接帮我选一个"
        deterministic = rewrite_query(message)
        result = await build_llm_query_rewrite(message, deterministic=deterministic)
        selected, selection = select_query_rewrite(deterministic, result, min_confidence=0.78)

        assert result.status == "success"
        assert selection is not None
        assert selection.status == "low_confidence"
        assert selection.accepted is False
        assert selected == deterministic

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()


def test_openai_llm_rewrite_missing_key_disables_before_network(
    run_async: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NetworkShouldNotBeCalled:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("OpenAI rewrite should disable before creating an HTTP client.")

    monkeypatch.setenv("LLM_REWRITE_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr("app.services.llm_query_rewrite.httpx.AsyncClient", NetworkShouldNotBeCalled)
    get_settings.cache_clear()

    async def scenario() -> None:
        deterministic = rewrite_query("我在北京鼓楼，想吃川菜")
        result = await build_llm_query_rewrite("我在北京鼓楼，想吃川菜", deterministic=deterministic)

        assert result.enabled is False
        assert result.status == "disabled"
        assert "key" in str(result.error).lower()

    try:
        run_async(scenario)
    finally:
        get_settings.cache_clear()
