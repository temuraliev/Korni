"""event_photos: multiple photos per event (event card + teacher info)

Revision ID: 0002_event_photos
Revises: 0001_initial
Create Date: 2026-04-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_event_photos"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ENUM через DO-блок: идемпотентно, не ломается на остатках от прошлых деплоев.
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE event_photo_kind AS ENUM ('event', 'teacher'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )

    kind_col = postgresql.ENUM("event", "teacher", name="event_photo_kind", create_type=False)

    op.create_table(
        "event_photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", kind_col, nullable=False, server_default="event"),
        sa.Column("file_id", sa.String(256), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_event_photos_event_id", "event_photos", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_event_photos_event_id", table_name="event_photos")
    op.drop_table("event_photos")
    sa.Enum(name="event_photo_kind").drop(op.get_bind(), checkfirst=True)
