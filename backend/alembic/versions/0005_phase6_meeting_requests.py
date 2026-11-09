"""phase 6: meeting requests -- duration, the manager's reply note, indexes

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09 14:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('meeting_requests', sa.Column('duration_minutes', sa.Integer(), server_default='30', nullable=False))
    op.add_column('meeting_requests', sa.Column('reply_note', sa.String(length=1000), nullable=True))
    op.create_check_constraint('meeting_duration_valid', 'meeting_requests',
                               'duration_minutes BETWEEN 15 AND 240')
    op.create_index('ix_meeting_requests_company_status', 'meeting_requests', ['company_id', 'status'])
    op.create_index('ix_meeting_requests_requested_by', 'meeting_requests', ['company_id', 'requested_by'])
    op.create_index('ix_notifications_user_unread', 'notifications', ['company_id', 'user_id', 'read_at'])


def downgrade() -> None:
    op.drop_index('ix_notifications_user_unread', table_name='notifications')
    op.drop_index('ix_meeting_requests_requested_by', table_name='meeting_requests')
    op.drop_index('ix_meeting_requests_company_status', table_name='meeting_requests')
    op.drop_constraint('meeting_duration_valid', 'meeting_requests', type_='check')
    op.drop_column('meeting_requests', 'reply_note')
    op.drop_column('meeting_requests', 'duration_minutes')
