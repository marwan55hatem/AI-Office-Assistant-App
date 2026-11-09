"""phase 5: e-mail queue and user e-mail preferences

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09 10:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

APP_ROLE = "office_app"

# The background sender works for every company, but the app role sees one company at a
# time (RLS). This SECURITY DEFINER function tells it only *which* companies have e-mail
# due; it then handles each company inside that company's own tenant context.
DUE_COMPANIES = """
CREATE FUNCTION email_due_companies(p_limit integer) RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT DISTINCT e.company_id FROM email_log e
    WHERE e.status = 'queued' AND (e.next_attempt_at IS NULL OR e.next_attempt_at <= now())
    LIMIT p_limit
$$;
"""


def upgrade() -> None:
    op.add_column('users', sa.Column('email_notifications', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('users', sa.Column('language', sa.String(length=2), server_default='en', nullable=False))
    op.create_check_constraint('language_valid', 'users', "language IN ('en', 'ar')")
    op.add_column('email_log', sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()),
                                         server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column('email_log', sa.Column('urgent', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('email_log', sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_email_log_due', 'email_log', ['status', 'next_attempt_at'], unique=False)
    op.execute(DUE_COMPANIES)
    op.execute(f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        GRANT EXECUTE ON FUNCTION email_due_companies(integer) TO {APP_ROLE};
    END IF;
END $$;
""")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS email_due_companies(integer)")
    op.drop_index('ix_email_log_due', table_name='email_log')
    op.drop_column('email_log', 'next_attempt_at')
    op.drop_column('email_log', 'urgent')
    op.drop_column('email_log', 'payload')
    op.drop_constraint('language_valid', 'users', type_='check')
    op.drop_column('users', 'language')
    op.drop_column('users', 'email_notifications')
