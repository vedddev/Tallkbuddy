"""Add opt-in history setting and idempotent message storage.

Revision ID: 20261115_02
Revises: 20261115_01
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261115_02"
down_revision: str | None = "20261115_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column("save_history_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("translation_messages", sa.Column("idempotency_key", sa.String(length=36), nullable=True))
    op.add_column("translation_messages", sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_translation_messages_session_request",
        "translation_messages",
        ["session_id", "idempotency_key"],
    )
    op.create_index(
        "ix_translation_messages_session_created",
        "translation_messages",
        ["session_id", "created_at", "id"],
    )
    op.create_index(
        "ix_translation_sessions_user_started",
        "translation_sessions",
        ["user_id", "started_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_translation_sessions_user_started", table_name="translation_sessions")
    op.drop_index("ix_translation_messages_session_created", table_name="translation_messages")
    op.drop_constraint(
        "uq_translation_messages_session_request", "translation_messages", type_="unique"
    )
    op.drop_column("translation_messages", "request_fingerprint")
    op.drop_column("translation_messages", "idempotency_key")
    op.drop_column("user_preferences", "save_history_enabled")
