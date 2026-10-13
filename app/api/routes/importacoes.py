from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, select

from app.api.deps import TenantDB
from app.api.routes._helpers import get_or_404
from app.models import Conta, Importacao, Transacao
from app.schemas.importacao import (
    ErroLinha,
    ImportacaoOut,
    PreviewOut,
    ResultadoImportacaoOut,
    SugestaoMapeamento,
)
from app.services.csv_extrato import (
    ExtratoInvalido,
    Formato,
    Mapeamento,
    Tabela,
    detectar_formato,
    ler_tabela,
    sugerir_mapeamento,
)
from app.services.importacao import importar, obter_ou_criar_conta

router = APIRouter(prefix="/importacoes", tags=["importacoes"])

MAX_BYTES = 5 * 1024 * 1024

CONTA_SUGERIDA = {
    Formato.nubank_conta: "Nubank - Conta",
    Formato.nubank_cartao: "Nubank - Cartão",
    Formato.generico: "Minha conta",
}


async def _ler_arquivo(arquivo: UploadFile) -> Tabela:
    conteudo = await arquivo.read(MAX_BYTES + 1)
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Arquivo maior que 5 MB")
    try:
        return ler_tabela(conteudo)
    except ExtratoInvalido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


def _out(imp: Importacao) -> ImportacaoOut:
    return ImportacaoOut(
        id=imp.id,
        conta_id=imp.conta_id,
        conta_nome=imp.conta.nome,
        nome_arquivo=imp.nome_arquivo,
        formato=imp.formato,
        total_linhas=imp.total_linhas,
        importadas=imp.importadas,
        duplicadas=imp.duplicadas,
        com_erro=imp.com_erro,
        created_at=imp.created_at,
    )


@router.post("/preview", response_model=PreviewOut)
async def preview(arquivo: Annotated[UploadFile, File()], tdb: TenantDB) -> PreviewOut:
    """Lê o arquivo sem salvar nada: formato detectado, colunas e primeiras linhas."""
    tabela = await _ler_arquivo(arquivo)
    formato = detectar_formato(tabela.colunas)
    linhas = [linha for linha in tabela.linhas if linha]
    return PreviewOut(
        formato=formato,
        colunas=tabela.colunas,
        amostra=linhas[:5],
        total_linhas=len(linhas),
        sugestao=SugestaoMapeamento(**sugerir_mapeamento(tabela.colunas)),
        conta_sugerida=CONTA_SUGERIDA[formato],
    )


@router.post("", response_model=ResultadoImportacaoOut, status_code=status.HTTP_201_CREATED)
async def criar(
    tdb: TenantDB,
    arquivo: Annotated[UploadFile, File()],
    conta_id: Annotated[int | None, Form()] = None,
    conta_nome: Annotated[str | None, Form(max_length=120)] = None,
    coluna_data: Annotated[str | None, Form()] = None,
    coluna_descricao: Annotated[str | None, Form()] = None,
    coluna_valor: Annotated[str | None, Form()] = None,
    gastos_positivos: Annotated[bool, Form()] = False,
) -> ResultadoImportacaoOut:
    """Importa o extrato para uma conta existente (`conta_id`) ou nova/por nome (`conta_nome`).

    Nubank é reconhecido automaticamente; para outros bancos, informe as colunas.
    Lançamentos que a conta já tem são ignorados (reimportar não duplica).
    """
    tabela = await _ler_arquivo(arquivo)
    formato = detectar_formato(tabela.colunas)
    mapeamento = None
    if formato == Formato.generico:
        if not (coluna_data and coluna_descricao and coluna_valor):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Formato não reconhecido: informe as colunas de data, descrição e valor",
            )
        mapeamento = Mapeamento(coluna_data, coluna_descricao, coluna_valor, gastos_positivos)

    if conta_id is not None:
        # Filtrada por tenant: conta de outro tenant = não encontrada.
        conta = tdb.get(Conta, conta_id)
        if conta is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Conta não encontrada")
    elif conta_nome and conta_nome.strip():
        conta = obter_ou_criar_conta(tdb, conta_nome.strip(), formato)
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Informe a conta do extrato")

    try:
        resumo = importar(
            tdb,
            tabela=tabela,
            formato=formato,
            mapeamento=mapeamento,
            conta=conta,
            nome_arquivo=arquivo.filename or "extrato.csv",
        )
    except ExtratoInvalido as exc:
        tdb.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    tdb.commit()
    tdb.refresh(resumo.importacao)
    return ResultadoImportacaoOut(
        importacao=_out(resumo.importacao),
        meses=resumo.meses,
        erros=[ErroLinha(linha=linha, motivo=motivo) for linha, motivo in resumo.erros],
    )


@router.get("", response_model=list[ImportacaoOut])
def listar(tdb: TenantDB) -> list[ImportacaoOut]:
    return [_out(i) for i in tdb.scalars(select(Importacao).order_by(Importacao.id.desc()))]


@router.delete("/{importacao_id}", status_code=status.HTTP_204_NO_CONTENT)
def desfazer(importacao_id: int, tdb: TenantDB) -> Response:
    """Remove a importação e os lançamentos que ela criou."""
    imp = get_or_404(tdb, Importacao, importacao_id, "Importação")
    # DELETE em massa também passa pelo filtro de tenant da sessão.
    tdb.session.execute(delete(Transacao).where(Transacao.importacao_id == imp.id))
    tdb.delete(imp)
    tdb.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
