"""dialog_messages: лог переписки для админки

Revision ID: 0004_dialog_messages
Revises: 0003_drop_total_seats
Create Date: 2026-04-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_dialog_messages"
down_revision: Union[str, None] = "0003_drop_total_seats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE dialog_direction AS ENUM ('in', 'out'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    direction_col = postgresql.ENUM("in", "out", name="dialog_direction", create_type=False)

    op.create_table(
        "dialog_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("direction", direction_col, nullable=False),
        sa.Column("content_type", sa.String(16), nullable=False),
        sa.Column("text", sa.Text()),
        sa.Column("file_id", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_dialog_messages_user_tg_id", "dialog_messages", ["user_tg_id"])
    op.create_index("ix_dialog_messages_created_at", "dialog_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_dialog_messages_created_at", table_name="dialog_messages")
    op.drop_index("ix_dialog_messages_user_tg_id", table_name="dialog_messages")
    op.drop_table("dialog_messages")
    sa.Enum(name="dialog_direction").drop(op.get_bind(), checkfirst=True)
