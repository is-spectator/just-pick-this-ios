from __future__ import annotations

import app.agent as agent_entrypoints
import app.agent.pipi_chat_graph as pipi_chat_graph


OLD_BUSINESS_NODES = {
    "rewrite_query",
    "retrieve_knowledge",
    "evaluate_evidence",
    "decide_next_action",
    "execute_tool",
    "respond",
}

WRAPPER_NODES = {
    "__start__",
    "__end__",
    "persist_turn",
    "input_gate",
    "build_context",
    "direct_answer",
    "run_pipi_loop",
    "persist_response",
}


def _compiled_node_names() -> set[str]:
    graph = pipi_chat_graph.build_pipi_chat_graph()
    compiled = getattr(graph, "_compiled_graph", graph)
    return set(getattr(compiled, "nodes", {}).keys())


def test_pipi_chat_graph_main_path_excludes_old_business_nodes() -> None:
    nodes = _compiled_node_names()

    assert OLD_BUSINESS_NODES.isdisjoint(nodes)
    assert nodes <= WRAPPER_NODES
    assert {
        "persist_turn",
        "input_gate",
        "build_context",
        "run_pipi_loop",
        "persist_response",
    }.issubset(nodes)


def test_agent_package_does_not_export_old_business_nodes() -> None:
    exported = set(getattr(agent_entrypoints, "__all__", ()))

    assert OLD_BUSINESS_NODES.isdisjoint(exported)
    for name in OLD_BUSINESS_NODES:
        assert not hasattr(agent_entrypoints, name)


def test_deprecated_module_compatibility_aliases_are_not_graph_nodes() -> None:
    for name in OLD_BUSINESS_NODES:
        legacy_callable = getattr(pipi_chat_graph, name)
        assert callable(legacy_callable)
        assert legacy_callable.__name__.startswith("_deprecated_")
