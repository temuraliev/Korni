"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(128)),
        sa.Column("last_name", sa.String(128)),
        sa.Column("phone", sa.String(32)),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_users_tg_id", "users", ["tg_id"], unique=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("emoji", sa.String(8)),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("teacher_info", sa.Text()),
        sa.Column("photo_file_id", sa.String(256)),
        sa.Column("event_date", sa.DateTime(timezone=True)),
        sa.Column("total_seats", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_events_category_id", "events", ["category_id"])

    # Создаём ENUM-типы через DO-блок: идемпотентно, не зависит от того, остались ли
    # они от прошлых неудачных деплоев.
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE booking_status AS ENUM ('pending', 'confirmed', 'cancelled'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE callback_status AS ENUM ('pending', 'done'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )

    booking_status_col = postgresql.ENUM(
        "pending", "confirmed", "cancelled", name="booking_status", create_type=False
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("status", booking_status_col, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"])
    op.create_index("ix_bookings_event_id", "bookings", ["event_id"])

    callback_status_col = postgresql.ENUM(
        "pending", "done", name="callback_status", create_type=False
    )
    op.create_table(
        "callbacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="SET NULL")),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("status", callback_status_col, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_callbacks_user_id", "callbacks", ["user_id"])

    op.create_table(
        "message_map",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("admin_group_message_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("user_message_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_message_map_user_tg_id", "message_map", ["user_tg_id"])
    op.create_index("ix_message_map_admin_group_message_id", "message_map", ["admin_group_message_id"], unique=True)

    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("photo_file_id", sa.String(256)),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("broadcasts")
    op.drop_table("message_map")
    op.drop_table("callbacks")
    sa.Enum(name="callback_status").drop(op.get_bind(), checkfirst=True)
    op.drop_table("bookings")
    sa.Enum(name="booking_status").drop(op.get_bind(), checkfirst=True)
    op.drop_table("events")
    op.drop_table("categories")
    op.drop_table("users")
