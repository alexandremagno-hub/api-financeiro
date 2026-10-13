"""importacao de extratos

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('importacoes',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('conta_id', sa.BigInteger(), nullable=False),
    sa.Column('nome_arquivo', sa.String(length=255), nullable=False),
    sa.Column('formato', sa.String(length=30), nullable=False),
    sa.Column('total_linhas', sa.Integer(), nullable=False),
    sa.Column('importadas', sa.Integer(), nullable=False),
    sa.Column('duplicadas', sa.Integer(), nullable=False),
    sa.Column('com_erro', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conta_id'], ['contas.id'], name=op.f('fk_importacoes_conta_id_contas'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_importacoes_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_importacoes'))
    )
    op.create_index(op.f('ix_importacoes_conta_id'), 'importacoes', ['conta_id'], unique=False)
    op.create_index(op.f('ix_importacoes_tenant_id'), 'importacoes', ['tenant_id'], unique=False)
    op.add_column('categorias', sa.Column('fora_do_resumo', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('transacoes', sa.Column('id_externo', sa.String(length=64), nullable=True))
    op.add_column('transacoes', sa.Column('importacao_id', sa.BigInteger(), nullable=True))
    op.create_index(op.f('ix_transacoes_importacao_id'), 'transacoes', ['importacao_id'], unique=False)
    op.create_unique_constraint(op.f('uq_transacoes_tenant_id_conta_id_id_externo'), 'transacoes', ['tenant_id', 'conta_id', 'id_externo'])
    op.create_foreign_key(op.f('fk_transacoes_importacao_id_importacoes'), 'transacoes', 'importacoes', ['importacao_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_transacoes_importacao_id_importacoes'), 'transacoes', type_='foreignkey')
    op.drop_constraint(op.f('uq_transacoes_tenant_id_conta_id_id_externo'), 'transacoes', type_='unique')
    op.drop_index(op.f('ix_transacoes_importacao_id'), table_name='transacoes')
    op.drop_column('transacoes', 'importacao_id')
    op.drop_column('transacoes', 'id_externo')
    op.drop_column('categorias', 'fora_do_resumo')
    # Índices que sustentam FKs caem junto com a tabela (o MySQL recusa dropá-los antes).
    op.drop_table('importacoes')
