from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import app.jobs.finalizer_job as finalizer_job
from app.services.chat import finalize_help_card_now


APP_ROOT = Path(__file__).resolve().parents[1]


def test_legacy_finalize_helper_delegates_to_pipi_finalize_graph(monkeypatch: Any) -> None:
    calls: list[tuple[Any, uuid.UUID]] = []
    session = object()
    final_card = object()
    help_card_id = uuid.uuid4()
    help_card = SimpleNamespace(
        id=help_card_id,
        answer_count=3,
        min_answers_required=3,
        final_recommendation_card=None,
    )

    def fake_run_finalize_graph_for_help_card(session_arg: Any, card_id: uuid.UUID) -> dict[str, Any]:
        calls.append((session_arg, card_id))
        help_card.final_recommendation_card = final_card
        return {
            "status": "final_ready",
            "final_recommendation_card": {"id": str(uuid.uuid4())},
        }

    monkeypatch.setattr(
        finalizer_job,
        "run_finalize_graph_for_help_card",
        fake_run_finalize_graph_for_help_card,
    )

    assert finalize_help_card_now(session, help_card=help_card) is final_card
    assert calls == [(session, help_card_id)]


def test_product_code_does_not_call_legacy_finalize_helper() -> None:
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        relative = path.relative_to(APP_ROOT)
        if relative.parts and relative.parts[0] == "tests":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            calls_legacy_helper = (
                isinstance(func, ast.Name)
                and func.id == "finalize_help_card_now"
                or isinstance(func, ast.Attribute)
                and func.attr == "finalize_help_card_now"
            )
            if calls_legacy_helper:
                offenders.append(f"{relative}:{node.lineno}")

    assert offenders == []
