from __future__ import annotations

from types import SimpleNamespace

from app.services.image_policy_metrics import image_policy_summary_from_records


def _card(
    id: str,
    *,
    image_asset_id: str | None = None,
    payload_json: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        image_asset_id=image_asset_id,
        payload_json=payload_json or {},
    )


def _image(
    id: str,
    *,
    verified: bool,
    displayable: bool,
    is_ai_generated: bool,
    source_url: str | None,
    source_domain: str | None,
    verification_status: str = "verified",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        verified=verified,
        displayable=displayable,
        is_ai_generated=is_ai_generated,
        source_url=source_url,
        source_domain=source_domain,
        verification_status=verification_status,
    )


def test_image_policy_summary_tracks_attach_and_bad_image_rates() -> None:
    summary = image_policy_summary_from_records(
        cards=[
            _card("trusted-card", image_asset_id="trusted-image"),
            _card("bad-card", image_asset_id="bad-image"),
            _card("no-image-card", payload_json={"evidence_ids": ["evidence-1"]}),
        ],
        images=[
            _image(
                "trusted-image",
                verified=True,
                displayable=True,
                is_ai_generated=False,
                source_url="https://example.com/photo",
                source_domain="example.com",
            ),
            _image(
                "bad-image",
                verified=True,
                displayable=True,
                is_ai_generated=False,
                source_url=None,
                source_domain=None,
            ),
        ],
        window_hours=24,
    )

    assert summary["counts"] == {
        "recommendation_card_count": 3,
        "image_attached_card_count": 2,
        "trusted_image_card_count": 1,
        "bad_image_card_count": 1,
        "missing_image_card_count": 1,
        "no_image_with_evidence_count": 1,
    }
    assert summary["rates"] == {
        "image_attach_rate": 0.6667,
        "trusted_image_rate": 0.5,
        "bad_image_rate": 0.5,
        "no_image_with_evidence_rate": 1.0,
    }
    assert summary["bad_image_items"][0]["card_id"] == "bad-card"
    assert summary["bad_image_items"][0]["issues"] == [
        "image_missing_source_url",
        "image_missing_source_domain",
    ]
    assert summary["metadata"]["contract"].startswith("images are optional")


def test_image_policy_summary_handles_no_cards() -> None:
    summary = image_policy_summary_from_records(cards=[], images=[])

    assert summary["counts"]["recommendation_card_count"] == 0
    assert summary["rates"]["image_attach_rate"] is None
    assert summary["rates"]["bad_image_rate"] is None
    assert summary["rates"]["no_image_with_evidence_rate"] is None
