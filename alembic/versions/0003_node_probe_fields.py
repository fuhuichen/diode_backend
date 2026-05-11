"""add probe fields to nodes table

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('nodes', sa.Column('probe_ok', sa.Boolean(), nullable=True))
    op.add_column('nodes', sa.Column('probe_latency_ms', sa.Float(), nullable=True))
    op.add_column('nodes', sa.Column('probe_error', sa.String(500), nullable=True))
    op.add_column('nodes', sa.Column('probe_fail_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('nodes', sa.Column('last_probe_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('nodes', 'last_probe_at')
    op.drop_column('nodes', 'probe_fail_count')
    op.drop_column('nodes', 'probe_error')
    op.drop_column('nodes', 'probe_latency_ms')
    op.drop_column('nodes', 'probe_ok')
