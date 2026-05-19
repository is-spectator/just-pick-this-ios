"""database runtime model

Revision ID: 0001_database_model_skeleton
Revises:
Create Date: 2026-05-19
"""

from collections.abc import Sequence

from alembic import op

from app.db import Base
from app import models  # noqa: F401

revision: str = "0001_database_model_skeleton"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
