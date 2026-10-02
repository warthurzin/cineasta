from pydantic import BaseModel

from app.llm import extrair_json


class VerificacaoResposta(BaseModel):
    suportada: bool
    observacao: str = ""


def interpretar_verificacao(texto: str) -> VerificacaoResposta:
    return VerificacaoResposta.model_validate(extrair_json(texto))