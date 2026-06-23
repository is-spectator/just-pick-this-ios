"""align recommendation card image foreign key

Revision ID: 0003_card_image_fk
Revises: 0002_optional_images
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003_card_image_fk"
down_revision: str | None = "0002_optional_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FK_NAME = "fk_recommendation_cards_image_asset_id_image_assets"


def _image_asset_fk() -> dict | None:
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys("recommendation_cards"):
        if (
            foreign_key.get("constrained_columns") == ["image_asset_id"]
            and foreign_key.get("referred_table") == "image_assets"
        ):
            return foreign_key
    return None


def _drop_image_asset_fk() -> None:
    foreign_key = _image_asset_fk()
    if foreign_key is not None and foreign_key.get("name"):
        op.drop_constraint(foreign_key["name"], "recommendation_cards", type_="foreignkey")


def upgrade() -> None:
    foreign_key = _image_asset_fk()
    if foreign_key is not None and foreign_key.get("options", {}).get("ondelete") == "SET NULL":
        return

    _drop_image_asset_fk()
    op.create_foreign_key(
        FK_NAME,
        "recommendation_cards",
        "image_assets",
        ["image_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    _drop_image_asset_fk()
    op.create_foreign_key(
        FK_NAME,
        "recommendation_cards",
        "image_assets",
        ["image_asset_id"],
        ["id"],
    )
