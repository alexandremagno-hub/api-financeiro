from datetime import datetime

from app.schemas.common import OutputModel
from app.services.csv_extrato import Formato


class SugestaoMapeamento(OutputModel):
    coluna_data: str | None
    coluna_descricao: str | None
    coluna_valor: str | None


class PreviewOut(OutputModel):
    formato: Formato
    colunas: list[str]
    amostra: list[dict[str, str]]
    total_linhas: int
    sugestao: SugestaoMapeamento
    conta_sugerida: str


class ErroLinha(OutputModel):
    linha: int
    motivo: str


class ImportacaoOut(OutputModel):
    id: int
    conta_id: int
    conta_nome: str
    nome_arquivo: str
    formato: str
    total_linhas: int
    importadas: int
    duplicadas: int
    com_erro: int
    created_at: datetime


class ResultadoImportacaoOut(OutputModel):
    importacao: ImportacaoOut
    meses: list[str]
    erros: list[ErroLinha]
