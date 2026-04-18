"""drop events.total_seats (seat-count feature removed)

Revision ID: 0003_drop_total_seats
Revises: 0002_event_photos
Create Date: 2026-04-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_drop_total_seats"
down_revision: Union[str, None] = "0002_event_photos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Идемпотентно: если колонки уже нет — пропускаем.
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS total_seats;")


def downgrade() -> None:
    op.add_column(
        "events",
        sa.Column("total_seats", sa.Integer(), nullable=False, server_default="0"),
    )
