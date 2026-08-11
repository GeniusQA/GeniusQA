"""add agent_task and agent_artifact tables + AI test task menu

Revision ID: a1b2c3d4e5f8
Revises: 3cb253e67619
Create Date: 2026-08-10 19:30:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = 'a1b2c3d4e5f8'
down_revision = '3cb253e67619'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'agent_task',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False, comment='任务名称'),
        sa.Column('pipeline_type', sa.String(length=20), nullable=False, server_default='api', comment='流水线类型'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending', comment='任务状态'),
        sa.Column('project_id', sa.BigInteger(), nullable=True, comment='关联项目ID'),
        sa.Column('env_name', sa.String(length=50), nullable=True, comment='执行环境'),
        sa.Column('input_file', sa.String(length=255), nullable=True, comment='需求文档'),
        sa.Column('exec_mode', sa.String(length=10), nullable=False, server_default='manual', comment='执行模式'),
        sa.Column('model_tier', sa.String(length=20), nullable=True, server_default='standard', comment='模型档位'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0', comment='进度'),
        sa.Column('current_node', sa.String(length=30), nullable=True, comment='当前节点'),
        sa.Column('error_msg', sa.Text(), nullable=True, comment='失败原因'),
        sa.Column('token_used', sa.Integer(), nullable=False, server_default='0', comment='Token'),
        sa.Column('cost', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0', comment='成本'),
        sa.Column('trace', mysql.JSON(), nullable=True, comment='轨迹'),
        sa.Column('artifacts', mysql.JSON(), nullable=True, comment='产物索引'),
        sa.Column('creation_date', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('updation_date', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sa.BigInteger(), nullable=True),
        sa.Column('enabled_flag', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('trace_id', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_charset='utf8mb4',
        comment='AI 测试任务表'
    )
    op.create_index('idx_agent_task_status', 'agent_task', ['status'])
    op.add_column('agent_task', sa.Column('case_config', mysql.JSON(), nullable=True, comment='用例生成配置'))
    op.create_index('idx_agent_task_created', 'agent_task', ['creation_date'])

    op.create_table(
        'agent_artifact',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('task_id', sa.BigInteger(), nullable=False, comment='任务ID'),
        sa.Column('kind', sa.String(length=20), nullable=False, comment='产物类型'),
        sa.Column('content', mysql.JSON(), nullable=True, comment='产物内容'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1', comment='版本'),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='draft', comment='状态'),
        sa.Column('summary', sa.String(length=500), nullable=True, comment='摘要'),
        sa.Column('creation_date', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('updation_date', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sa.BigInteger(), nullable=True),
        sa.Column('enabled_flag', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('trace_id', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_charset='utf8mb4',
        comment='AI 测试任务产物表'
    )
    op.create_index('idx_agent_artifact_task', 'agent_artifact', ['task_id'])

    # 菜单：AI 管理(92) 下新增「AI 测试任务」页面菜单
    op.execute("""
        INSERT INTO `sys_menu`
        (id, menu_name, menu_type, parent_id, path, component, query, perms, icon,
         order_num, visible, status, is_frame, is_cache, remark,
         creation_date, created_by, updation_date, updated_by, enabled_flag, trace_id, created_at, updated_at)
        VALUES
        (4138, 'AI测试任务', 'C', 92, '/ai/agent-tasks', 'ai/agent-tasks/index', NULL, NULL, 'ele-MagicStick',
         3, 1, 1, 1, 0, '多 Agent 接口自动化测试任务中心',
         '2026-08-10 19:30:00', 1, '2026-08-10 19:30:00', 1, 1, NULL, '2026-08-10 19:30:00', '2026-08-10 19:30:00')
    """)
    op.execute("INSERT INTO sys_role_menu (role_id, menu_id) SELECT id, 4138 FROM sys_role WHERE role_key='admin' ON DUPLICATE KEY UPDATE menu_id=menu_id")


def downgrade() -> None:
    op.execute("DELETE FROM sys_role_menu WHERE menu_id = 4138")
    op.execute("DELETE FROM sys_menu WHERE id = 4138")
    op.drop_index('idx_agent_artifact_task', table_name='agent_artifact')
    op.drop_table('agent_artifact')
    op.drop_index('idx_agent_task_status', table_name='agent_task')
    op.drop_index('idx_agent_task_created', table_name='agent_task')
    op.drop_table('agent_task')
