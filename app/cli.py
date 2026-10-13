"""Criação de tenants pelo servidor (alternativa ao POST /auth/signup, ex.: backoffice).

Uso:
    python -m app.cli criar-tenant --nome "Empresa X" --admin-email admin@x.com --admin-nome "Admin"
A senha é lida do prompt (ou da env ADMIN_PASSWORD, para automação).
"""

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.core.security import SENHA_MIN_CARACTERES, hash_password
from app.db.session import SessionLocal
from app.models import Role, Tenant, Usuario


def criar_tenant(nome: str, admin_email: str, admin_nome: str, senha: str) -> None:
    with SessionLocal() as db:
        email = admin_email.lower()
        if db.scalar(select(Usuario.id).where(Usuario.email == email)):
            sys.exit(f"E-mail já cadastrado: {email}")
        tenant = Tenant(nome=nome)
        db.add(tenant)
        db.flush()
        db.add(
            Usuario(
                tenant_id=tenant.id,
                email=email,
                nome=admin_nome,
                senha_hash=hash_password(senha),
                role=Role.admin,
            )
        )
        db.commit()
        print(f"Tenant {tenant.id} ({nome}) criado com admin {email}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("criar-tenant")
    p.add_argument("--nome", required=True)
    p.add_argument("--admin-email", required=True)
    p.add_argument("--admin-nome", required=True)
    args = parser.parse_args()

    if args.cmd == "criar-tenant":
        senha = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Senha do admin: ")
        if len(senha) < SENHA_MIN_CARACTERES:
            sys.exit(f"A senha precisa ter pelo menos {SENHA_MIN_CARACTERES} caracteres")
        criar_tenant(args.nome, args.admin_email, args.admin_nome, senha)


if __name__ == "__main__":
    main()
