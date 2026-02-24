"""usage bytes tracking: replace usage_count with usage_bytes, add bytes_up/bytes_down to connections

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add bytes_up and bytes_down to connections
    op.add_column('connections', sa.Column('bytes_up', sa.BigInteger(), nullable=False, server_default='0'))
    op.add_column('connections', sa.Column('bytes_down', sa.BigInteger(), nullable=False, server_default='0'))

    # Add usage_bytes to applications
    op.add_column('applications', sa.Column('usage_bytes', sa.BigInteger(), nullable=False, server_default='0'))

    # Remove usage_count from applications
    op.drop_column('applications', 'usage_count')

    # Update existing usage_limit values to 1 GB (1073741824 bytes)
    op.execute("UPDATE applications SET usage_limit = 1073741824")


def downgrade() -> None:
    # Re-add usage_count
    op.add_column('applications', sa.Column('usage_count', sa.BigInteger(), nullable=False, server_default='0'))

    # Remove usage_bytes
    op.drop_column('applications', 'usage_bytes')

    # Remove bytes columns from connections
    op.drop_column('connections', 'bytes_down')
    op.drop_column('connections', 'bytes_up')

    # Revert usage_limit to old default
    op.execute("UPDATE applications SET usage_limit = 5")
