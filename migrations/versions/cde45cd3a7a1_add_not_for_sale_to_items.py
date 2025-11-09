"""add not_for_sale to items

Revision ID: cde45cd3a7a1
Revises: 8c85042925db
Create Date: 2025-10-09 14:59:04.029576

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cde45cd3a7a1'
down_revision: Union[str, Sequence[str], None] = '8c85042925db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
