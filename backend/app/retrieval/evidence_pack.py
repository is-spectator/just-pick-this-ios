"""Normalize retrieval hits into a compact evidence pack.

The pack is intentionally side-effect free: it does not call web providers,
does not score taste quality, and does not create cards. Its job is to make
retrieval context readable for the reasoner, trace replay, and eval reports.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from app.harness.evidence_evaluator import evidence_layers_for_payload, is_card_ready_hit


EVIDENCE_PACK_VERSION = "evidence_pack_v1"
MAX_STRONGEST_EVIDENCE = 5


LOCAL_MEMORY_SOURCE_TYPES = {"intent_answer", "recommendation_card", "knowledge_fact"}
HUMAN_EVIDENCE_SOURCE_TYPES = {"help_answer"}
WEB_SOURCE_TYPES = {"web_result"}
IMAGE_SOURCE_TYPES = {"image_asset"}
PLACE_SOURCE_TYPES = {"amap_poi_candidate", "local_area_poi_fallback"}


def build_evidence_pack(
    hits: Sequence[Mapping[str, Any]] | None,
    *,
    retrieval_run: Mapping[str, Any] | None = None,
    max_items: int = MAX_STRONGEST_EVIDENCE,
) -> dict[str, Any]:
    """Return a stable evidence pack for context and trace consumers."""

    normalized_hits = [_normalize_hit(hit) for hit in list(hits or []) if isinstance(hit, Mapping)]
    strongest = sorted(
        normalized_hits,
        key=lambda item: float(item.get("score") or 0.0),
        reverse=True,
    )[: max(1, max_items)]
    flags = _pack_flags(normalized_hits)
    return {
        "version": EVIDENCE_PACK_VERSION,
        "retrieval_run_id": _retrieval_run_id(retrieval_run),
        "query": _retrieval_query(retrieval_run),
        "hit_count": len(normalized_hits),
        "layers": _layer_summaries(normalized_hits),
        "strongest_evidence": strongest,
        "missing_layers": _missing_layers(flags),
        **flags,
    }


def summarize_evidence_pack(pack: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a small summary safe to embed in metadata."""

    if not isinstance(pack, Mapping):
        return {
            "version": EVIDENCE_PACK_VERSION,
            "hit_count": 0,
            "layer_counts": {},
            "missing_layers": [
                "local_memory",
                "human_evidence",
                "web_evidence",
                "verified_image",
                "place_evidence",
            ],
        }
    layer_counts = {
        str(layer.get("type")): int(layer.get("count") or 0)
        for layer in pack.get("layers", [])
        if isinstance(layer, Mapping) and layer.get("type")
    }
    return {
        "version": str(pack.get("version") or EVIDENCE_PACK_VERSION),
        "retrieval_run_id": pack.get("retrieval_run_id"),
        "hit_count": int(pack.get("hit_count") or 0),
        "layer_counts": layer_counts,
        "missing_layers": list(pack.get("missing_layers") or []),
        "has_card_ready_evidence": bool(pack.get("has_card_ready_evidence")),
        "has_local_memory": bool(pack.get("has_local_memory")),
        "has_human_evidence": bool(pack.get("has_human_evidence")),
        "has_web_evidence": bool(pack.get("has_web_evidence")),
        "has_verified_image": bool(pack.get("has_verified_image")),
        "has_place_evidence": bool(pack.get("has_place_evidence")),
    }


def _normalize_hit(hit: Mapping[str, Any]) -> dict[str, Any]:
    payload = _payload(hit)
    source_type = _source_type(hit, payload)
    layers = _layers(source_type, payload)
    evidence_id = _first_string(
        hit.get("evidence_id"),
        hit.get("source_id"),
        payload.get("retrieval_hit_id"),
    )
    return {
        "id": evidence_id,
        "source_type": source_type,
        "layers": layers,
        "title": _first_string(hit.get("title"), payload.get("card_title"), payload.get("title")),
        "text": _first_string(hit.get("snippet"), hit.get("text"), payload.get("reference_answer")),
        "score": _score(hit),
        "card_ready": is_card_ready_hit(hit),
        "source_id": _first_string(hit.get("source_id"), payload.get("source_id")),
        "image_asset_id": _first_string(hit.get("image_asset_id"), payload.get("image_asset_id")),
        "intent_answer_id": _first_string(payload.get("intent_answer_id"), payload.get("reference_intent_answer_id")),
        "help_answer_id": _first_string(payload.get("help_answer_id")),
        "help_card_id": _first_string(payload.get("help_card_id")),
        "recommendation_card_id": _first_string(payload.get("recommendation_card_id")),
        "place": _compact_place(payload.get("place")),
        "action_type": _action_type(payload.get("action")),
    }


def _pack_flags(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "has_local_memory": any(_has_any(item, LOCAL_MEMORY_SOURCE_TYPES) for item in items),
        "has_human_evidence": any(_has_any(item, HUMAN_EVIDENCE_SOURCE_TYPES) or "human_answer" in item.get("layers", []) for item in items),
        "has_web_evidence": any(_has_any(item, WEB_SOURCE_TYPES) or "web_result" in item.get("layers", []) for item in items),
        "has_verified_image": any(_has_any(item, IMAGE_SOURCE_TYPES) or "image_asset" in item.get("layers", []) for item in items),
        "has_place_evidence": any(_has_any(item, PLACE_SOURCE_TYPES) or "amap_poi" in item.get("layers", []) for item in items),
        "has_route_evidence": any("route" in item.get("layers", []) for item in items),
        "has_card_ready_evidence": any(bool(item.get("card_ready")) for item in items),
    }


def _layer_summaries(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    best_scores: dict[str, float] = {}
    for item in items:
        for layer in item.get("layers", []):
            layer_name = str(layer)
            counts[layer_name] += 1
            best_scores[layer_name] = max(best_scores.get(layer_name, 0.0), float(item.get("score") or 0.0))
    return [
        {"type": name, "count": count, "best_score": round(best_scores.get(name, 0.0), 3)}
        for name, count in sorted(counts.items())
    ]


def _missing_layers(flags: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    if not flags.get("has_local_memory"):
        missing.append("local_memory")
    if not flags.get("has_human_evidence"):
        missing.append("human_evidence")
    if not flags.get("has_web_evidence"):
        missing.append("web_evidence")
    if not flags.get("has_verified_image"):
        missing.append("verified_image")
    if not flags.get("has_place_evidence"):
        missing.append("place_evidence")
    return missing


def _layers(source_type: str, payload: Mapping[str, Any]) -> list[str]:
    layers = evidence_layers_for_payload(payload)
    if source_type in LOCAL_MEMORY_SOURCE_TYPES:
        layers.append("local_memory")
    if source_type in HUMAN_EVIDENCE_SOURCE_TYPES:
        layers.append("human_answer")
    if source_type in WEB_SOURCE_TYPES:
        layers.append("web_result")
    if source_type in IMAGE_SOURCE_TYPES:
        layers.append("image_asset")
    if source_type in PLACE_SOURCE_TYPES:
        layers.append("amap_poi")
    return list(dict.fromkeys(layer for layer in layers if layer))


def _payload(hit: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = hit.get("payload") or hit.get("metadata") or {}
    return payload if isinstance(payload, Mapping) else {}


def _source_type(hit: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    return _first_string(hit.get("source_type"), hit.get("hit_type"), payload.get("source_type")) or "unknown"


def _retrieval_run_id(retrieval_run: Mapping[str, Any] | None) -> str | None:
    if not isinstance(retrieval_run, Mapping):
        return None
    return _first_string(retrieval_run.get("id"), retrieval_run.get("retrieval_run_id"))


def _retrieval_query(retrieval_run: Mapping[str, Any] | None) -> str | None:
    if not isinstance(retrieval_run, Mapping):
        return None
    return _first_string(retrieval_run.get("query"))


def _score(hit: Mapping[str, Any]) -> float:
    try:
        return round(float(hit.get("score") or 0.0), 3)
    except (TypeError, ValueError):
        return 0.0


def _compact_place(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    location = value.get("location")
    compact_location = dict(location) if isinstance(location, Mapping) else None
    return {
        "provider": value.get("provider"),
        "poi_id": value.get("poi_id"),
        "name": value.get("name"),
        "address": value.get("address"),
        "location": compact_location,
    }


def _action_type(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    return _first_string(value.get("type"))


def _has_any(item: Mapping[str, Any], source_types: set[str]) -> bool:
    source_type = str(item.get("source_type") or "")
    return source_type in source_types


def _first_string(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


__all__ = ["EVIDENCE_PACK_VERSION", "build_evidence_pack", "summarize_evidence_pack"]
