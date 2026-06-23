from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any


DEFAULT_EXPERIMENTS: tuple[dict[str, Any], ...] = (
    {
        "experiment_id": "pipi_card_copy_v1",
        "variants": ("control", "concise_copy"),
        "version": 1,
    },
)


def resolve_experiment_assignments(
    *,
    user_id: str | None = None,
    device_uid: str | None = None,
    conversation_id: str | None = None,
    client_context: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return stable experiment assignments for trace and behavior metrics.

    Assignments are observation-only in this V0 slice: they must not alter
    routing, prompt selection, tool calls, or card rendering.
    """

    client_context = dict(client_context or {})
    metadata = dict(metadata or {})
    provided = _normalise_provided_assignments(
        metadata.get("experiment_assignments")
        or client_context.get("experiment_assignments")
        or client_context.get("experiments")
    )
    assigned_by_id = {item["experiment_id"]: item for item in provided}
    assignment_key = str(user_id or device_uid or conversation_id or "anonymous")
    for spec in DEFAULT_EXPERIMENTS:
        experiment_id = str(spec["experiment_id"])
        if experiment_id in assigned_by_id:
            continue
        assigned_by_id[experiment_id] = _assign_from_spec(spec, assignment_key=assignment_key)
    return list(assigned_by_id.values())


def experiment_metadata(assignments: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    items = [dict(item) for item in assignments or [] if isinstance(item, Mapping)]
    return {
        "assignments": items,
        "variant_ids": {
            str(item.get("experiment_id")): str(item.get("variant_id"))
            for item in items
            if item.get("experiment_id") and item.get("variant_id")
        },
    }


def merge_experiment_metadata(
    payload: Mapping[str, Any] | None,
    assignments: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    merged = dict(payload or {})
    if "experiment_assignments" not in merged:
        merged["experiment_assignments"] = [dict(item) for item in assignments or []]
    if "experiment_variant_ids" not in merged:
        merged["experiment_variant_ids"] = experiment_metadata(assignments)["variant_ids"]
    return merged


def _assign_from_spec(spec: Mapping[str, Any], *, assignment_key: str) -> dict[str, Any]:
    experiment_id = str(spec["experiment_id"])
    variants = tuple(str(item) for item in spec.get("variants") or ("control",))
    digest = hashlib.sha256(f"{experiment_id}:{assignment_key}".encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % max(1, len(variants))
    return {
        "experiment_id": experiment_id,
        "variant_id": variants[index],
        "source": "server_hash",
        "version": int(spec.get("version") or 1),
        "assignment_key_hash": digest[:16],
    }


def _normalise_provided_assignments(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        items = []
        for experiment_id, variant in value.items():
            if isinstance(variant, Mapping):
                item = {
                    "experiment_id": str(variant.get("experiment_id") or experiment_id),
                    "variant_id": str(variant.get("variant_id") or variant.get("variant") or ""),
                    "source": str(variant.get("source") or "client"),
                    "version": int(variant.get("version") or 1),
                }
            else:
                item = {
                    "experiment_id": str(experiment_id),
                    "variant_id": str(variant),
                    "source": "client",
                    "version": 1,
                }
            if item["experiment_id"] and item["variant_id"]:
                items.append(item)
        return items
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = []
        for raw_item in value:
            if not isinstance(raw_item, Mapping):
                continue
            experiment_id = str(raw_item.get("experiment_id") or raw_item.get("id") or "")
            variant_id = str(raw_item.get("variant_id") or raw_item.get("variant") or "")
            if not experiment_id or not variant_id:
                continue
            items.append(
                {
                    "experiment_id": experiment_id,
                    "variant_id": variant_id,
                    "source": str(raw_item.get("source") or "client"),
                    "version": int(raw_item.get("version") or 1),
                }
            )
        return items
    return []


def experiment_assignments_from_payload(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    payload = dict(payload or {})
    return _normalise_provided_assignments(
        payload.get("experiment_assignments")
        or payload.get("experiments")
        or payload.get("experiment")
    )
