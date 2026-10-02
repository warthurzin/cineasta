from typing import Literal

from pydantic import BaseModel, field_validator

from app.llm import extrair_json


class AnalisePergunta(BaseModel):
    categoria: Literal["FILMES", "AMBIGUA", "FORA_DOMINIO"]
    pergunta_autonoma: str = ""
    manipulacao: bool = False
    confianca: Literal["ALTA", "MEDIA", "BAIXA"] = "MEDIA"

    @field_validator("categoria", "confianca", mode="before")
    @classmethod
    def _normalizar_caixa(cls, valor):
        if isinstance(valor, str):
            return valor.strip().upper()
        return valor


def interpretar_analise(texto: str) -> AnalisePergunta:
    analise = AnalisePergunta.model_validate(extrair_json(texto))

    if analise.categoria == "FILMES" and not analise.pergunta_autonoma.strip():
        raise ValueError("categoria FILMES exige pergunta_autonoma preenchida")

    return analise