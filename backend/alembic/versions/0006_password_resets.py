"""password reset links

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-11 10:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

APP_ROLE = "office_app"

# Using a reset link happens before the company is known (like an invite): this SECURITY
# DEFINER lookup returns only what the reset needs, for one token hash.
FIND = """
CREATE FUNCTION auth_find_password_reset(p_hash text)
RETURNS TABLE (id uuid, company_id uuid, user_id uuid, expires_at timestamptz, used_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT r.id, r.company_id, r.user_id, r.expires_at, r.used_at
    FROM password_resets r WHERE r.token_hash = p_hash
$$;
"""


def upgrade() -> None:
    op.create_table('password_resets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['company_id', 'user_id'], ['users.company_id', 'users.id'], name='fk_password_resets_user', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_password_resets_company_id'), 'password_resets', ['company_id'], unique=False)
    op.execute("ALTER TABLE password_resets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE password_resets FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON password_resets "
               "USING (company_id = app_current_company()) WITH CHECK (company_id = app_current_company())")
    op.execute(FIND)
    op.execute(f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON password_resets TO {APP_ROLE};
        GRANT EXECUTE ON FUNCTION auth_find_password_reset(text) TO {APP_ROLE};
    END IF;
END $$;
""")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_find_password_reset(text)")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON password_resets")
    op.drop_index(op.f('ix_password_resets_company_id'), table_name='password_resets')
    op.drop_table('password_resets')
