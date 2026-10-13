"""schema inicial

Revision ID: 0001
Revises: 
Create Date: 2026-10-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('tenants',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenants'))
    )
    op.create_table('categorias',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('categoria_pai_id', sa.BigInteger(), nullable=True),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['categoria_pai_id'], ['categorias.id'], name=op.f('fk_categorias_categoria_pai_id_categorias'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_categorias_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categorias')),
    sa.UniqueConstraint('tenant_id', 'categoria_pai_id', 'nome', name=op.f('uq_categorias_tenant_id_categoria_pai_id_nome'))
    )
    op.create_index(op.f('ix_categorias_categoria_pai_id'), 'categorias', ['categoria_pai_id'], unique=False)
    op.create_index(op.f('ix_categorias_tenant_id'), 'categorias', ['tenant_id'], unique=False)
    op.create_table('contas',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('tipo', sa.Enum('carteira', 'corrente', 'cartao_credito', name='tipoconta', native_enum=False, length=20), nullable=False),
    sa.Column('saldo_inicial_centavos', sa.BigInteger(), nullable=False),
    sa.Column('ativa', sa.Boolean(), nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_contas_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contas')),
    sa.UniqueConstraint('tenant_id', 'nome', name=op.f('uq_contas_tenant_id_nome'))
    )
    op.create_index(op.f('ix_contas_tenant_id'), 'contas', ['tenant_id'], unique=False)
    op.create_table('usuarios',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('nome', sa.String(length=120), nullable=False),
    sa.Column('senha_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('admin', 'usuario', name='role', native_enum=False, length=20), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_usuarios_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usuarios')),
    sa.UniqueConstraint('email', name=op.f('uq_usuarios_email'))
    )
    op.create_index(op.f('ix_usuarios_tenant_id'), 'usuarios', ['tenant_id'], unique=False)
    op.create_table('transacoes',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('conta_id', sa.BigInteger(), nullable=False),
    sa.Column('categoria_id', sa.BigInteger(), nullable=True),
    sa.Column('tipo', sa.Enum('receita', 'despesa', name='tipotransacao', native_enum=False, length=20), nullable=False),
    sa.Column('valor_centavos', sa.BigInteger(), nullable=False),
    sa.Column('descricao', sa.String(length=255), nullable=False),
    sa.Column('data_competencia', sa.Date(), nullable=False),
    sa.Column('data_lancamento', sa.Date(), nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('valor_centavos > 0', name=op.f('ck_transacoes_valor_positivo')),
    sa.ForeignKeyConstraint(['categoria_id'], ['categorias.id'], name=op.f('fk_transacoes_categoria_id_categorias'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['conta_id'], ['contas.id'], name=op.f('fk_transacoes_conta_id_contas'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_transacoes_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transacoes'))
    )
    op.create_index(op.f('ix_transacoes_categoria_id'), 'transacoes', ['categoria_id'], unique=False)
    op.create_index(op.f('ix_transacoes_conta_id'), 'transacoes', ['conta_id'], unique=False)
    op.create_index('ix_transacoes_tenant_competencia', 'transacoes', ['tenant_id', 'data_competencia'], unique=False)
    op.create_index(op.f('ix_transacoes_tenant_id'), 'transacoes', ['tenant_id'], unique=False)
    op.create_index('ix_transacoes_tenant_lancamento', 'transacoes', ['tenant_id', 'data_lancamento'], unique=False)


def downgrade() -> None:
    # No MySQL não é possível dropar índices que sustentam FKs antes da tabela;
    # dropar as tabelas (em ordem reversa de dependência) remove os índices junto.
    op.drop_table("transacoes")
    op.drop_table("usuarios")
    op.drop_table("contas")
    op.drop_table("categorias")
    op.drop_table("tenants")
