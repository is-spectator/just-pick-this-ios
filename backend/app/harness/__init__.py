"""Governance layer for the Pipi agent runtime."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from app.harness.trace_store import TraceStore


_LAZY_EXPORTS = {
    "AnswerGate": ("app.harness.answer_gate", "AnswerGate"),
    "ContextBuilder": ("app.harness.context_builder", "ContextBuilder"),
    "Evaluator": ("app.harness.evaluator", "Evaluator"),
    "EvaluationResult": ("app.harness.evaluator", "EvaluationResult"),
    "InputGate": ("app.harness.input_gate", "InputGate"),
    "InputGateResult": ("app.harness.input_gate", "InputGateResult"),
    "PipiContextBuilder": ("app.harness.context_builder", "PipiContextBuilder"),
    "PipiContextPack": ("app.harness.context_builder", "PipiContextPack"),
    "evaluate_help_card": ("app.harness.evaluator", "evaluate_help_card"),
    "evaluate_recommendation_card": (
        "app.harness.evaluator",
        "evaluate_recommendation_card",
    ),
    "run_input_gate": ("app.harness.input_gate", "run_input_gate"),
}

__all__ = ["TraceStore", *_LAZY_EXPORTS]


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'app.harness' has no attribute {name!r}")

    module_name, attr_name = _LAZY_EXPORTS[name]
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise AttributeError(f"module {module_name!r} is not available") from exc
        raise
    if not hasattr(module, attr_name) and name == "evaluate_help_card":

        def evaluate_help_card(help_card: Any) -> Any:
            return module.Evaluator().evaluate_help_card(help_card)

        value = evaluate_help_card
    elif not hasattr(module, attr_name) and name == "evaluate_recommendation_card":

        def evaluate_recommendation_card(card: Any) -> Any:
            return module.Evaluator().evaluate_recommendation_card(card)

        value = evaluate_recommendation_card
    else:
        value = getattr(module, attr_name)
    globals()[name] = value
    return value
