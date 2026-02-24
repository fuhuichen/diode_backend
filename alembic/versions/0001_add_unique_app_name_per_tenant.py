"""add unique constraint on app name per tenant

Revision ID: 0001
Revises:
Create Date: 2026-02-24
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        'uq_applications_tenant_id_name',
        'applications',
        ['tenant_id', 'name'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_applications_tenant_id_name', 'applications', type_='unique')
