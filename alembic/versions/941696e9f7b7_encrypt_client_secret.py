"""encrypt_client_secret

Revision ID: 941696e9f7b7
Revises: f6a7b8c9d1e2
Create Date: 2026-04-15 09:59:41.246661

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from cryptography.fernet import Fernet


# revision identifiers, used by Alembic.
revision: str = '941696e9f7b7'
down_revision: Union[str, None] = 'f6a7b8c9d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_fernet() -> Fernet:
    """Load ENCRYPTION_KEY from settings (already validated at import time)."""
    from app.config import settings
    if not settings.ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY must be set to run this migration")
    return Fernet(settings.ENCRYPTION_KEY.encode())


def upgrade() -> None:
    # 1. Add new column
    op.add_column("accounts", sa.Column("client_secret_encrypted", sa.Text(), nullable=True))

    # 2. Encrypt existing plaintext values
    conn = op.get_bind()
    f = _get_fernet()
    rows = conn.execute(
        sa.text("SELECT id, client_secret FROM accounts WHERE client_secret IS NOT NULL")
    ).fetchall()
    for row in rows:
        encrypted = f.encrypt(row[1].encode()).decode()
        conn.execute(
            sa.text("UPDATE accounts SET client_secret_encrypted = :enc WHERE id = :id"),
            {"enc": encrypted, "id": row[0]},
        )

    # 3. Drop old column, rename new one
    op.drop_column("accounts", "client_secret")
    op.alter_column("accounts", "client_secret_encrypted", new_column_name="client_secret")


def downgrade() -> None:
    # 1. Add plaintext column back
    op.add_column("accounts", sa.Column("client_secret_plain", sa.Text(), nullable=True))

    # 2. Decrypt values back to plaintext
    conn = op.get_bind()
    f = _get_fernet()
    rows = conn.execute(
        sa.text("SELECT id, client_secret FROM accounts WHERE client_secret IS NOT NULL")
    ).fetchall()
    for row in rows:
        try:
            decrypted = f.decrypt(row[1].encode()).decode()
        except Exception:
            decrypted = row[1]  # Already plaintext or corrupted — keep as-is
        conn.execute(
            sa.text("UPDATE accounts SET client_secret_plain = :plain WHERE id = :id"),
            {"plain": decrypted, "id": row[0]},
        )

    # 3. Drop encrypted column, rename plaintext back
    op.drop_column("accounts", "client_secret")
    op.alter_column("accounts", "client_secret_plain", new_column_name="client_secret")
