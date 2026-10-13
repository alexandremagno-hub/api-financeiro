"""Importa lançamentos de um extrato para uma conta do tenant atual."""

from dataclasses import dataclass, field

from sqlalchemy import select

from app.db.tenant import TenantSession
from app.models import Conta, Importacao, TipoConta, TipoTransacao, Transacao
from app.services.categorizacao import garantir_categorias_padrao, sugerir_categoria
from app.services.csv_extrato import Formato, Mapeamento, Tabela, interpretar

MAX_ERROS_DETALHADOS = 50


@dataclass
class ResumoImportacao:
    importacao: Importacao
    meses: list[str] = field(default_factory=list)  # "AAAA-MM" com lançamentos novos
    erros: list[tuple[int, str]] = field(default_factory=list)


def obter_ou_criar_conta(tdb: TenantSession, nome: str, formato: Formato) -> Conta:
    conta = tdb.scalars(select(Conta).where(Conta.nome == nome))
    if conta:
        return conta[0]
    tipo = TipoConta.cartao_credito if formato == Formato.nubank_cartao else TipoConta.corrente
    conta = tdb.add(Conta(nome=nome, tipo=tipo))
    tdb.flush()
    return conta


def importar(
    tdb: TenantSession,
    *,
    tabela: Tabela,
    formato: Formato,
    mapeamento: Mapeamento | None,
    conta: Conta,
    nome_arquivo: str,
) -> ResumoImportacao:
    resultado = interpretar(tabela, formato, mapeamento)
    categorias = garantir_categorias_padrao(tdb)

    # Deduplicação: IDs externos que esta conta já tem (consulta filtrada por tenant).
    ids = [lanc.id_externo for lanc in resultado.lancamentos]
    existentes: set[str] = set()
    for i in range(0, len(ids), 1000):
        existentes.update(
            tdb.scalars(
                select(Transacao.id_externo).where(
                    Transacao.conta_id == conta.id, Transacao.id_externo.in_(ids[i : i + 1000])
                )
            )
        )

    importacao = tdb.add(
        Importacao(
            conta_id=conta.id,
            nome_arquivo=nome_arquivo[:255],
            formato=formato.value,
            total_linhas=sum(1 for linha in tabela.linhas if linha),
            com_erro=len(resultado.erros),
        )
    )
    tdb.flush()

    meses: set[str] = set()
    vistos: set[str] = set()
    importadas = duplicadas = 0
    for lanc in resultado.lancamentos:
        if lanc.id_externo in existentes or lanc.id_externo in vistos:
            duplicadas += 1
            continue
        vistos.add(lanc.id_externo)
        tdb.add(
            Transacao(
                conta_id=conta.id,
                categoria_id=categorias[sugerir_categoria(lanc.descricao)].id,
                tipo=TipoTransacao.despesa if lanc.valor_centavos < 0 else TipoTransacao.receita,
                valor_centavos=abs(lanc.valor_centavos),
                descricao=lanc.descricao,
                data_competencia=lanc.data,
                data_lancamento=lanc.data,
                id_externo=lanc.id_externo,
                importacao_id=importacao.id,
            )
        )
        importadas += 1
        meses.add(lanc.data.strftime("%Y-%m"))

    importacao.importadas = importadas
    importacao.duplicadas = duplicadas
    return ResumoImportacao(importacao, sorted(meses), resultado.erros[:MAX_ERROS_DETALHADOS])
